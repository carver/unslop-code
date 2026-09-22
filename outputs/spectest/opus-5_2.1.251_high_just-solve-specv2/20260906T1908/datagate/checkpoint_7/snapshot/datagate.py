"""datagate - convert remote CSV files into queryable JSON datasets.

Usage:
    python datagate.py start --port <port> --address <address>
"""

from __future__ import annotations

import argparse
import codecs
import csv
import datetime as _datetime
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from collections import Counter
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"

DEFAULT_ROW_LIMIT = 100
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT = 30

# Control parameters understood by /datasets/<id>. Every one of them may appear
# at most once per request; anything else in the query string is ignored.
CONTROL_PARAMS = (
    "_size",
    "_offset",
    "_shape",
    "_sort",
    "_sort_desc",
    "_rowid",
    "_total",
)
SHAPES = ("lists", "objects")
HIDE = "hide"

# Filters take the form `<column>__<comparator>=<value>`. A name starting with
# "_" is a control parameter and a name without the separator is not a filter
# at all; both are left alone here.
FILTER_SEPARATOR = "__"
COMPARATORS = ("exact", "contains", "less", "greater")
NUMERIC_COMPARATORS = ("less", "greater")

# Wall-clock budget for evaluating one /datasets/<id> query.
QUERY_TIMEOUT = 5.0

# The first row of the source file is the header, so the first data row is 2.
FIRST_DATA_ROWID = 2

# Minimum required delimiters are "," ";" and "\t"; "|" and ":" are supported
# as a bonus but are only ever chosen when they clearly structure the input.
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
FALLBACK_ENCODING = "latin-1"

_ID_LENGTH = 16

# Multipart field names accepted by /upload, in priority order.
UPLOAD_FIELDS = ("file", "attachment")
MULTIPART_MIMETYPE = "multipart/form-data"

# Source formats understood by /convert and /upload.
FORMAT_TEXT = "text"
FORMAT_XLSX = "xlsx"
FORMAT_XLS = "xls"

# `.xlsx` is a zip container; `.xls` is an OLE2 compound document.
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_XLSX_MARKERS = ("xl/workbook.xml", "xl/workbook.bin")

MAX_UPLOAD_BYTES = MAX_DOWNLOAD_BYTES

EXPORT_MIMETYPE = "text/csv"
EXPORT_NEWLINE = "\r\n"

# Settings come from three places, each overriding the one before it: the
# built-in defaults below, the `DATAGATE_CONFIG` file, and finally the
# environment itself. Anything that cannot be understood stops the server
# from starting rather than being guessed at, because a service running with
# a misread size limit or allowlist is worse than a service that never came up.
CONFIG_FILE_VAR = "DATAGATE_CONFIG"

MAX_SOURCE_SIZE_VAR = "MAX_SOURCE_SIZE"
ORIGIN_ALLOWLIST_VAR = "ORIGIN_ALLOWLIST"
REQUIRE_TLS_VAR = "REQUIRE_TLS"
STORAGE_DIR_VAR = "STORAGE_DIR"
CACHE_ENV_VAR = "CACHE_ENABLED"

SETTING_VARS = (
    MAX_SOURCE_SIZE_VAR,
    ORIGIN_ALLOWLIST_VAR,
    REQUIRE_TLS_VAR,
    STORAGE_DIR_VAR,
    CACHE_ENV_VAR,
)

# Boolean spellings are exhaustive: matched case-insensitively after trimming,
# and nothing else is accepted.
BOOL_TRUE_VALUES = ("1", "true", "yes", "on")
BOOL_FALSE_VALUES = ("0", "false", "no", "off")

DEFAULT_CACHE_ENABLED = True
DEFAULT_REQUIRE_TLS = False
DEFAULT_MAX_SOURCE_SIZE = None
DEFAULT_ORIGIN_ALLOWLIST: Tuple[str, ...] = ()

# Where datasets live when `STORAGE_DIR` says nothing: a private directory of
# this process. Sharing datasets between runs is what `STORAGE_DIR` is for, so
# an unconfigured server never picks up another one's leftovers.
DEFAULT_STORAGE_DIRNAME_TEMPLATE = "datagate-store-%d"

# One dataset per file, named after its id.
_STORE_SUFFIX = ".json"

# Comment lines in a config file.
CONFIG_COMMENT_PREFIXES = ("#",)

# The list separator inside one config value.
CONFIG_LIST_SEPARATOR = ","

# The header that has to name an allowed origin once an allowlist is set.
REFERER_HEADER = "Referer"

# `force` is a presence flag on /convert: `?force` re-ingests, `?force=1` is a
# mistake worth reporting rather than guessing at.
FORCE_PARAM = "force"

# `enrich` is the opt-in for ingestion-time dataset metadata on /convert. It
# is deliberately not a flag and not a boolean: exactly one `enrich=yes` turns
# enrichment on and every other state -- a different spelling, padding, a bare
# `?enrich`, a repeat -- leaves it off. Guessing at "y", "YES" or "true" would
# quietly change what gets stored, so an unrecognised spelling is simply not
# an opt-in rather than an error the caller has to handle.
ENRICH_PARAM = "enrich"
ENRICH_VALUE = "yes"

# `filetype` as reported by an enriched `dataset_summary`. Both workbook
# formats are one `excel`, because the distinction is a container detail the
# dataset itself no longer carries.
FILETYPE_CSV = "csv"
FILETYPE_EXCEL = "excel"

# Column type labels of an enriched `column_details`.
TYPE_TEXT = "text"
TYPE_NUMBER = "number"
TYPE_INTEGER = "integer"
TYPE_FLOAT = "float"

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class DatasetStore:
    """Thread-safe in-memory dataset store keyed by a deterministic id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._ingest_locks: Dict[str, threading.Lock] = {}
        self._dir: Optional[str] = None

    @staticmethod
    def make_id(source: str) -> str:
        """Deterministic id derived from the exact source URL string."""
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return digest[:_ID_LENGTH]

    @staticmethod
    def make_content_id(data: bytes) -> str:
        """Deterministic id derived from the exact uploaded bytes.

        Uploading the same bytes twice therefore always lands on the same
        dataset id, no matter what the part was called.
        """
        digest = hashlib.sha256(b"upload\x00" + data).hexdigest()
        return digest[:_ID_LENGTH]

    def put(self, dataset_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._data[dataset_id] = payload
            self._persist(dataset_id, payload)

    def get(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(dataset_id)

    def cached(self, dataset_id: str, key: Any) -> bool:
        """True when this id already holds the parse identified by `key`.

        The stored key is compared instead of a separate url -> id map so a
        dataset that was replaced by a different parse of the same URL (a new
        `charset`, say) cannot be served from a stale entry.
        """
        with self._lock:
            record = self._data.get(dataset_id)
            return record is not None and record.get("cache_key") == key

    def enriched(self, dataset_id: str) -> bool:
        """True when this id was stored by an enriching ingestion.

        Asked before serving /convert from the cache: a dataset parsed
        without enrichment cannot answer an enriched query, so it has to be
        ingested again rather than handed back as it stands.
        """
        with self._lock:
            record = self._data.get(dataset_id)
            return bool(record is not None and record.get("enriched"))

    def ingest_lock(self, dataset_id: str) -> threading.Lock:
        """The lock serialising ingestion of one dataset id.

        Concurrent requests for the same source then download once instead of
        racing each other; different sources never wait on one another.
        """
        with self._lock:
            lock = self._ingest_locks.get(dataset_id)
            if lock is None:
                lock = threading.Lock()
                self._ingest_locks[dataset_id] = lock
            return lock

    # -- persistence -----------------------------------------------------

    def configure(self, directory: Optional[str]) -> None:
        """Attach the store to `directory` and reload the datasets in it.

        Creating the directory is part of starting up, so one that cannot be
        created is a configuration failure rather than a surprise later on.
        """
        if directory is None:
            with self._lock:
                self._dir = None
            return
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise ConfigError(
                "Cannot create %s %r: %s"
                % (STORAGE_DIR_VAR, directory, _brief(exc))
            ) from None
        if not os.path.isdir(directory):
            raise ConfigError(
                "%s %r is not a directory." % (STORAGE_DIR_VAR, directory)
            )
        with self._lock:
            self._dir = directory
            self._restore()

    def _restore(self) -> None:
        """Load every dataset already written to the storage directory."""
        try:
            names = sorted(os.listdir(self._dir or "."))
        except OSError as exc:
            raise ConfigError(
                "Cannot read %s %r: %s"
                % (STORAGE_DIR_VAR, self._dir, _brief(exc))
            ) from None
        for name in names:
            if not name.endswith(_STORE_SUFFIX):
                continue
            dataset_id = name[: -len(_STORE_SUFFIX)]
            if not dataset_id:
                continue
            payload = _read_stored(os.path.join(self._dir or ".", name))
            if payload is not None:
                # Anything ingested since startup is newer than the file.
                self._data.setdefault(dataset_id, payload)

    def _persist(self, dataset_id: str, payload: Dict[str, Any]) -> None:
        """Write one dataset out so a restart can pick it up again.

        Best effort by design: a storage directory that has gone away must not
        turn a successful conversion into a failed request.
        """
        if self._dir is None:
            return
        key = payload.get("cache_key")
        record = {
            "source": payload.get("source", ""),
            "size": payload.get("size"),
            "columns": list(payload.get("columns", [])),
            "rows": [list(row) for row in payload.get("rows", [])],
            "cache_key": None if key is None else list(key),
            # Enrichment is part of what was stored, not of how it is asked
            # for, so a restart finds an enriched dataset still enriched.
            "enriched": bool(payload.get("enriched")),
            "dataset_summary": payload.get("dataset_summary"),
            "column_details": payload.get("column_details"),
        }
        target = os.path.join(self._dir, dataset_id + _STORE_SUFFIX)
        temp = "%s.%d.tmp" % (target, os.getpid())
        try:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, allow_nan=False)
            os.replace(temp, target)
        except (OSError, TypeError, ValueError):
            try:
                os.unlink(temp)
            except OSError:
                pass


def _read_stored(path: str) -> Optional[Dict[str, Any]]:
    """Read one persisted dataset back, or None when the file is unusable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    columns = record.get("columns")
    rows = record.get("rows")
    if not isinstance(columns, list) or not all(
        isinstance(name, str) for name in columns
    ):
        return None
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        return None
    source = record.get("source")
    size = record.get("size")
    key = record.get("cache_key")
    summary = record.get("dataset_summary")
    details = record.get("column_details")
    summary = summary if isinstance(summary, dict) else None
    details = details if isinstance(details, dict) else None
    # A file that claims enrichment without carrying a summary is unusable as
    # an enriched dataset, so it reads back as the plain dataset it can serve.
    enriched = bool(record.get("enriched")) and summary is not None
    return {
        "source": source if isinstance(source, str) else "",
        "size": size if isinstance(size, int) and not isinstance(size, bool) else None,
        "columns": columns,
        "rows": rows,
        "rowids": list(range(FIRST_DATA_ROWID, FIRST_DATA_ROWID + len(rows))),
        "cache_key": tuple(key) if isinstance(key, list) else None,
        "enriched": enriched,
        "dataset_summary": summary if enriched else None,
        "column_details": details if enriched else None,
    }


STORE = DatasetStore()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class DataGateError(Exception):
    """An error that maps onto a JSON error envelope."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class BadRequest(DataGateError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 400)


class NotFound(DataGateError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 404)


class UnsupportedMediaType(DataGateError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 415)


class ConfigError(Exception):
    """A bad environment setting: reported once, before the server starts."""


# --------------------------------------------------------------------------
# Service configuration
# --------------------------------------------------------------------------


class Config:
    """The resolved settings one datagate process runs with."""

    def __init__(
        self,
        max_source_size: Optional[int] = DEFAULT_MAX_SOURCE_SIZE,
        origin_allowlist: Sequence[str] = DEFAULT_ORIGIN_ALLOWLIST,
        require_tls: bool = DEFAULT_REQUIRE_TLS,
        storage_dir: Optional[str] = None,
        cache_enabled: bool = DEFAULT_CACHE_ENABLED,
    ) -> None:
        self.max_source_size = max_source_size
        self.origin_allowlist = tuple(origin_allowlist)
        self.require_tls = require_tls
        self.storage_dir = (
            default_storage_dir() if storage_dir is None else storage_dir
        )
        self.cache_enabled = cache_enabled

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            "Config(max_source_size=%r, origin_allowlist=%r, require_tls=%r, "
            "storage_dir=%r, cache_enabled=%r)"
            % (
                self.max_source_size,
                self.origin_allowlist,
                self.require_tls,
                self.storage_dir,
                self.cache_enabled,
            )
        )


def default_storage_dir() -> str:
    """The storage directory used when `STORAGE_DIR` is not configured."""
    return os.path.join(
        tempfile.gettempdir(), DEFAULT_STORAGE_DIRNAME_TEMPLATE % os.getpid()
    )


def parse_bool(name: str, raw: Optional[str], default: bool) -> bool:
    """Read one strict boolean setting.

    Values are trimmed and matched case-insensitively against the documented
    spellings. A value that merely looks boolean (`"maybe"`, `"2"`, `""`) is
    rejected rather than guessed at, because silently running with the
    opposite of what the operator asked for surfaces much later.
    """
    if raw is None:
        return default
    token = raw.strip().lower()
    if token in BOOL_TRUE_VALUES:
        return True
    if token in BOOL_FALSE_VALUES:
        return False
    raise ConfigError(
        "Invalid %s value %r: expected one of %s."
        % (
            name,
            raw,
            ", ".join(repr(v) for v in BOOL_TRUE_VALUES + BOOL_FALSE_VALUES),
        )
    )


def parse_cache_enabled(raw: Optional[str]) -> bool:
    """Read one `CACHE_ENABLED` spelling, defaulting to caching enabled."""
    return parse_bool(CACHE_ENV_VAR, raw, DEFAULT_CACHE_ENABLED)


def load_cache_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """Resolve `CACHE_ENABLED` from the environment."""
    source = os.environ if env is None else env
    return parse_cache_enabled(source.get(CACHE_ENV_VAR))


# ASCII digits only: `int()` would also accept other Unicode digit forms and
# surrounding underscores, neither of which belongs in a byte count.
_SIZE_RE = re.compile(r"[0-9]+")


def parse_size(name: str, raw: Optional[str]) -> Optional[int]:
    """Read one size setting in bytes, or None when it is not configured."""
    if raw is None:
        return None
    token = raw.strip()
    if not _SIZE_RE.fullmatch(token):
        raise ConfigError(
            "Invalid %s value %r: expected a non-negative whole number of "
            "bytes." % (name, raw)
        )
    return int(token)


def normalize_domain(raw: str) -> str:
    """Reduce one allowlist entry to a bare, lower-case domain suffix.

    Operators write suffixes in several shapes -- `example.com`,
    `.example.com`, `https://example.com/`, `example.com:8443` -- and all of
    them mean the same domain, so they are normalised to the same key.
    """
    text = raw.strip().lower()
    if not text:
        return ""
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if text.startswith("["):  # bracketed IPv6 literal
        text = text.partition("]")[0].lstrip("[")
    elif ":" in text:
        text = text.split(":", 1)[0]
    return text.strip(".")


def parse_allowlist(raw: Optional[str]) -> Tuple[str, ...]:
    """Read `ORIGIN_ALLOWLIST` into an ordered tuple of domain suffixes.

    An unset -- or empty -- list means "no allowlist", which lets every
    request through.
    """
    if raw is None:
        return DEFAULT_ORIGIN_ALLOWLIST
    suffixes: List[str] = []
    for item in raw.split(CONFIG_LIST_SEPARATOR):
        suffix = normalize_domain(item)
        if suffix and suffix not in suffixes:
            suffixes.append(suffix)
    return tuple(suffixes)


def parse_storage_dir(raw: Optional[str]) -> str:
    """Read `STORAGE_DIR`, falling back to the built-in default."""
    text = "" if raw is None else raw.strip()
    if not text:
        return default_storage_dir()
    return os.path.abspath(os.path.expanduser(text))


def read_config_file(path: str) -> Dict[str, str]:
    """Read a `KEY=VALUE` config file into raw, still-unvalidated strings.

    Blank lines and comments are ignored; a line that is neither and carries
    no `=` is a mistake in the file rather than something to skip over. The
    last spelling of a key wins, so a file can override its own earlier line.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(
            "Cannot read %s file %r: %s" % (CONFIG_FILE_VAR, path, _brief(exc))
        ) from None

    values: Dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith(CONFIG_COMMENT_PREFIXES):
            continue
        key, separator, value = entry.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ConfigError(
                "Invalid config in %r at line %d: expected KEY=VALUE, got %r."
                % (path, number, line)
            )
        values[key.upper()] = value.strip()
    return values


def load_config(env: Optional[Dict[str, str]] = None) -> Config:
    """Resolve every setting: defaults, then the config file, then the env."""
    source = os.environ if env is None else env

    settings: Dict[str, str] = {}
    config_path = (source.get(CONFIG_FILE_VAR) or "").strip()
    if config_path:
        settings.update(read_config_file(config_path))

    # Direct environment variables have the last word.
    for name in SETTING_VARS:
        value = source.get(name)
        if value is not None:
            settings[name] = value

    return Config(
        max_source_size=parse_size(
            MAX_SOURCE_SIZE_VAR, settings.get(MAX_SOURCE_SIZE_VAR)
        ),
        origin_allowlist=parse_allowlist(settings.get(ORIGIN_ALLOWLIST_VAR)),
        require_tls=parse_bool(
            REQUIRE_TLS_VAR, settings.get(REQUIRE_TLS_VAR), DEFAULT_REQUIRE_TLS
        ),
        storage_dir=parse_storage_dir(settings.get(STORAGE_DIR_VAR)),
        cache_enabled=parse_bool(
            CACHE_ENV_VAR, settings.get(CACHE_ENV_VAR), DEFAULT_CACHE_ENABLED
        ),
    )


# --------------------------------------------------------------------------
# Origin allowlist
# --------------------------------------------------------------------------


def referer_hostname(raw: Optional[str]) -> Optional[str]:
    """The lower-case host named by a `Referer` header, if it names one."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        host = urlsplit(text).hostname
        if not host and "://" not in text and not text.startswith("//"):
            # A bare `example.com/page` is not a valid referrer, but it names
            # a host plainly enough to be checked against the allowlist.
            host = urlsplit("//" + text).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.strip().lower().rstrip(".")


def host_allowed(hostname: Optional[str], allowlist: Sequence[str]) -> bool:
    """True when `hostname` sits at or under one of the allowed suffixes.

    Matching respects domain boundaries: `example.com` allows `example.com`
    and `data.example.com`, but never `notexample.com` or
    `example.com.evil.net`.
    """
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    for suffix in allowlist:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


# --------------------------------------------------------------------------
# URL validation
# --------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"http", "https"}


def validate_source(raw: Optional[str]) -> str:
    """Validate the `source` query parameter and return it unchanged."""
    if raw is None:
        raise BadRequest("Missing required query parameter: 'source'.")
    if not raw.strip():
        raise BadRequest("Query parameter 'source' must not be empty.")

    candidate = raw.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:  # malformed IPv6 literals, bad ports, ...
        raise BadRequest("Invalid URL: %s" % exc) from None

    if not parts.scheme:
        raise BadRequest(
            "Invalid URL: missing scheme (expected an http:// or https:// URL)."
        )
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BadRequest(
            "Invalid URL: unsupported scheme '%s' (expected http or https)."
            % parts.scheme
        )
    if not parts.netloc:
        raise BadRequest("Invalid URL: missing host.")

    hostname = None
    try:
        hostname = parts.hostname
        _ = parts.port  # raises ValueError for a non-numeric / out-of-range port
    except ValueError as exc:
        raise BadRequest("Invalid URL: %s" % exc) from None
    if not hostname:
        raise BadRequest("Invalid URL: missing host.")
    if any(ch.isspace() for ch in candidate):
        raise BadRequest("Invalid URL: URLs must not contain whitespace.")

    # Return the original string: the dataset id is derived from the exact
    # `source` value the caller supplied.
    return raw


def parse_force(args: Any) -> bool:
    """Read the `force` presence flag of a /convert request.

    `?force` and `?force=` both mean "re-ingest"; carrying a value means the
    caller expected `force` to be a switch with settings (`?force=0` reads as
    "do not force") so it is refused instead of being read as its opposite.
    """
    values = args.getlist(FORCE_PARAM)
    if not values:
        return False
    if len(values) > 1:
        raise BadRequest("Query parameter 'force' must not be repeated.")
    if values[0] != "":
        raise BadRequest(
            "Query parameter 'force' is a flag and takes no value, got %r."
            % values[0]
        )
    return True


def parse_enrich(args: Any) -> bool:
    """Read the `enrich` opt-in of a /convert request.

    Only one exact `enrich=yes` asks for enrichment. Anything else -- absent,
    repeated, empty, `ENRICH=YES`, ` yes`, `no` -- is not the opt-in and so
    leaves enrichment off; none of them is rejected, because `enrich` selects
    how much is computed rather than whether the request is well formed.
    """
    values = args.getlist(ENRICH_PARAM)
    return len(values) == 1 and values[0] == ENRICH_VALUE


def cache_key(source: str, charset_param: Optional[str]) -> Tuple[str, str]:
    """The cache identity of one /convert request.

    A different `charset` is a different parse of the same bytes, so it is part
    of the key. Valid names are normalised through `codecs` so `utf8` and
    `UTF-8` share an entry; anything else is kept verbatim (and simply never
    matches, since an undecodable request never gets stored).
    """
    if charset_param is None:
        name = ""
    else:
        try:
            name = validate_charset(charset_param) or ""
        except DataGateError:
            name = "?" + charset_param
    return (source, name)


# --------------------------------------------------------------------------
# Charset handling
# --------------------------------------------------------------------------


def validate_charset(raw: Optional[str]) -> Optional[str]:
    """Validate an explicit `charset` parameter, returning its codec name."""
    if raw is None:
        return None
    name = raw.strip()
    if not name:
        raise BadRequest("Query parameter 'charset' must not be empty.")
    if len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9._:+()\- ]+", name.replace("_", "")):
        raise BadRequest("Malformed charset: %r." % raw)
    try:
        info = codecs.lookup(name)
    except (LookupError, ValueError, TypeError):
        raise BadRequest("Unsupported charset: %r." % raw) from None

    # Reject non-text codecs such as base64/hex/zlib, which `codecs.lookup`
    # also resolves but which cannot decode bytes into text.
    if not getattr(info, "_is_text_encoding", True):
        raise BadRequest("Unsupported charset: %r." % raw)
    try:
        probe = b"".decode(info.name)
    except Exception:
        raise BadRequest("Unsupported charset: %r." % raw) from None
    if not isinstance(probe, str):
        raise BadRequest("Unsupported charset: %r." % raw)
    return info.name


_BOMS: List[Tuple[bytes, str]] = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]


def detect_encoding(data: bytes) -> str:
    """Detect an unambiguous encoding from content, else fall back to latin-1.

    The ladder is fully deterministic: byte-order marks first, then strict
    UTF-8 (a byte sequence that decodes as multi-byte UTF-8 is effectively
    never accidental), then BOM-less UTF-16 detected from NUL padding, and
    finally the latin-1 fallback which never fails.
    """
    if not data:
        return "utf-8"

    for bom, name in _BOMS:
        if data.startswith(bom):
            return name

    # Strict UTF-8 (a superset of ASCII).
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # BOM-less UTF-16: ASCII-dominant text shows a strong NUL pattern in one
    # of the two byte positions.
    sample = data[: 8192 - (8192 % 2)]
    if len(sample) >= 4:
        even_nul = sample[0::2].count(0)
        odd_nul = sample[1::2].count(0)
        half = len(sample) // 2
        if half:
            if odd_nul / half > 0.6 and even_nul == 0:
                try:
                    data.decode("utf-16-le")
                    return "utf-16-le"
                except UnicodeDecodeError:
                    pass
            if even_nul / half > 0.6 and odd_nul == 0:
                try:
                    data.decode("utf-16-be")
                    return "utf-16-be"
                except UnicodeDecodeError:
                    pass

    return FALLBACK_ENCODING


def decode_bytes(data: bytes, charset: Optional[str]) -> str:
    """Decode raw bytes using an explicit charset or a detected one."""
    if charset is not None:
        try:
            text = data.decode(charset)
        except UnicodeDecodeError:
            raise BadRequest(
                "Malformed charset: the source content could not be decoded "
                "as %r." % charset
            ) from None
        except (LookupError, ValueError, TypeError):
            raise BadRequest("Unsupported charset: %r." % charset) from None
    else:
        encoding = detect_encoding(data)
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            text = data.decode(FALLBACK_ENCODING)

    # A UTF-8 BOM can survive an explicit charset such as latin-1.
    if text.startswith("﻿"):
        text = text[1:]
    return text


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def source_too_large(size: int, limit: int, what: str) -> "BadRequest":
    """The 400 raised when a source is bigger than `MAX_SOURCE_SIZE`."""
    return BadRequest(
        "%s is too large: %d bytes exceeds the %s limit of %d bytes."
        % (what, size, MAX_SOURCE_SIZE_VAR, limit)
    )


def check_source_size(size: int, limit: Optional[int], what: str) -> None:
    """Enforce `MAX_SOURCE_SIZE`; a size equal to the limit is accepted."""
    if limit is not None and size > limit:
        raise source_too_large(size, limit, what)


def fetch_source(url: str, max_bytes: Optional[int] = None) -> bytes:
    """Download the source URL, mapping every transport failure onto 404.

    `max_bytes` is the configured `MAX_SOURCE_SIZE`: the download stops one
    byte past it, which is enough to tell "exactly at the limit" (accepted)
    from "over the limit" (rejected) without reading the rest of the body.
    """
    try:
        response = requests.get(
            url.strip(),
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "datagate/1.0",
                "Accept": "text/csv, text/plain, */*",
            },
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise NotFound("Source unreachable: %s" % _brief(exc)) from None
    except (ValueError, OSError) as exc:
        raise NotFound("Source unreachable: %s" % _brief(exc)) from None

    try:
        if response.status_code >= 400:
            raise NotFound(
                "Remote HTTP error %d for source." % response.status_code
            )
        hard_cap = (
            MAX_DOWNLOAD_BYTES
            if max_bytes is None
            else max(MAX_DOWNLOAD_BYTES, max_bytes + 1)
        )
        chunks: List[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise source_too_large(total, max_bytes, "Source")
                if total > hard_cap:
                    break
        except requests.exceptions.RequestException as exc:
            raise NotFound("Source unreachable: %s" % _brief(exc)) from None
        return b"".join(chunks)[:hard_cap]
    finally:
        response.close()


def _brief(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    text = " ".join(text.split())
    return text[:200]


# --------------------------------------------------------------------------
# Tabular detection & CSV parsing
# --------------------------------------------------------------------------

_CONTROL_ALLOWED = {"\t", "\n", "\r"}


def _looks_like_markup(text: str) -> bool:
    head = text.lstrip()[:4096]
    if not head:
        return False
    lowered = head.lower()
    if lowered.startswith(("<!doctype", "<?xml", "<html", "<rss", "<svg")):
        return True
    if head.startswith("<") and re.match(r"<\s*[A-Za-z!?/]", head):
        return True
    return False


def _looks_like_json(text: str) -> bool:
    head = text.strip()
    if not head or head[0] not in "{[":
        return False
    try:
        json.loads(head)
    except (ValueError, RecursionError):
        return False
    return True


def _looks_binary(text: str, raw: bytes) -> bool:
    if raw.startswith((b"%PDF", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"PK\x03\x04",
                       b"\x1f\x8b", b"BZh", b"\x7fELF", b"MZ", b"RIFF", b"OggS")):
        return True
    sample = text[:8192]
    if not sample:
        return False
    if "\x00" in sample:
        return True
    control = sum(
        1
        for ch in sample
        if (ord(ch) < 32 and ch not in _CONTROL_ALLOWED) or ord(ch) == 127
    )
    return control / len(sample) > 0.02


_PROSE_TERMINATORS = re.compile(r"[.!?](\s|$)")


def _looks_like_prose(rows: List[List[str]]) -> bool:
    """Heuristic guard for single-column parses of free-form text."""
    sample = [r[0] for r in rows[:20] if r and r[0].strip()]
    if not sample:
        return True
    header = sample[0].strip()
    if not header:
        return True
    if _PROSE_TERMINATORS.search(header):
        return True
    if len(header.split()) > 4:
        return True
    wordy = sum(1 for cell in sample if len(cell.split()) > 6)
    return wordy > len(sample) / 2


def _parse_with(text: str, delimiter: str) -> List[List[str]]:
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=delimiter,
        skipinitialspace=True,
    )
    rows: List[List[str]] = []
    try:
        for row in reader:
            rows.append(row)
    except csv.Error:
        return []
    return rows


def _drop_blank_rows(rows: List[List[str]]) -> List[List[str]]:
    return [r for r in rows if any(cell.strip() for cell in r)]


def _score(rows: List[List[str]]) -> Tuple[int, float, int]:
    """Score a candidate parse: (has structure, consistency, width)."""
    if len(rows) < 2:
        return (0, 0.0, 0)
    counts = Counter(len(r) for r in rows)
    width, hits = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    ratio = hits / len(rows)
    return (1 if width > 1 else 0, ratio, width)


def infer_and_parse(text: str) -> Tuple[List[str], List[List[str]]]:
    """Infer the delimiter and parse the document into a header and rows."""
    best: Optional[Tuple[Tuple[int, float, int], int, str, List[List[str]]]] = None

    for index, delimiter in enumerate(CANDIDATE_DELIMITERS):
        parsed = _drop_blank_rows(_parse_with(text, delimiter))
        if not parsed:
            continue
        score = _score(parsed)
        # Lower index wins ties, so `,` beats `;` beats `\t` beats `|`.
        key = (score, -index)
        if best is None or key > (best[0], -best[1]):
            best = (score, index, delimiter, parsed)

    if best is None:
        raise BadRequest(
            "Non-tabular content: the source does not contain a parsable table."
        )

    score, _index, _delimiter, rows = best

    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: a valid file requires at least one header "
            "row and one data row."
        )

    header_width = score[2]
    if header_width <= 1:
        # No delimiter present at all: only accept genuinely column-shaped
        # single-column data, not free-form prose.
        if _looks_like_prose(rows):
            raise BadRequest(
                "Non-tabular content: no delimiter could be inferred from the "
                "source."
            )

    header = [cell.strip() for cell in rows[0]]
    if not any(header):
        raise BadRequest("Non-tabular content: the header row is empty.")

    width = len(header)
    data: List[List[str]] = []
    for row in rows[1:]:
        if len(row) < width:
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        data.append([cell.strip() for cell in row])

    if not data:
        raise BadRequest(
            "Non-tabular content: a valid file requires at least one header "
            "row and one data row."
        )
    return header, data


def parse_tabular(raw: bytes, text: str) -> Tuple[List[str], List[List[str]]]:
    if not raw.strip() or not text.strip():
        raise BadRequest("Non-tabular content: the source is empty.")
    if _looks_binary(text, raw):
        raise BadRequest("Non-tabular content: the source appears to be binary.")
    if _looks_like_markup(text):
        raise BadRequest("Non-tabular content: the source appears to be markup.")
    if _looks_like_json(text):
        raise BadRequest("Non-tabular content: the source appears to be JSON.")
    return infer_and_parse(text)


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------

_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_TIME_RE = re.compile(
    r"""
    \d{1,2}
    :
    \d{1,2}
    (?::\d{1,2}(?:\.\d+)?)?
    (?:\s*[APap]\.?[Mm]\.?)?
    """,
    re.VERBOSE,
)


def _has_leading_zero(token: str) -> bool:
    digits = token.lstrip("+-")
    return len(digits) > 1 and digits[0] == "0"


def coerce(value: str) -> Any:
    """Deterministically coerce a CSV cell into its JSON representation.

    Integers and decimals become JSON numbers; everything else -- including
    time-like values such as `08:30`, `9:15` and `12:00` -- stays text.
    """
    token = value.strip()
    if not token:
        return value.strip()

    # Time-like values are checked first so `12:00` never looks numeric.
    if _TIME_RE.fullmatch(token):
        return token

    if _INT_RE.fullmatch(token):
        if _has_leading_zero(token):
            return token  # preserve zero-padded identifiers verbatim
        try:
            return int(token)
        except ValueError:
            return token

    if _FLOAT_RE.fullmatch(token):
        if _has_leading_zero(token.split(".")[0].split("e")[0].split("E")[0]):
            return token
        try:
            number = float(token)
        except (ValueError, OverflowError):
            return token
        if number != number or number in (float("inf"), float("-inf")):
            return token  # NaN / Infinity are not representable in JSON
        return number

    return token


# --------------------------------------------------------------------------
# Format detection
# --------------------------------------------------------------------------


def _zip_names(raw: bytes) -> Optional[List[str]]:
    """Member names of a zip container, or None when `raw` is not a zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            return archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, RuntimeError):
        return None


def detect_format(raw: bytes) -> str:
    """Classify the source bytes as a spreadsheet or as text.

    Detection is driven by content, never by a file name: a `.xls` extension
    on a CSV file is still a CSV file. Container formats that are recognised
    but are not workbooks are rejected outright.
    """
    if raw.startswith(_ZIP_MAGICS):
        names = _zip_names(raw)
        if names and any(name in _XLSX_MARKERS for name in names):
            return FORMAT_XLSX
        raise BadRequest(
            "Unrecognized format: the source is a zip archive but not an "
            "Excel workbook."
        )
    if raw.startswith(_OLE2_MAGIC):
        return FORMAT_XLS
    return FORMAT_TEXT


# --------------------------------------------------------------------------
# Spreadsheet ingestion
# --------------------------------------------------------------------------


def _cell_value(value: Any) -> Any:
    """Normalise one spreadsheet cell into its JSON representation."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        return value
    if isinstance(value, Decimal):
        return _cell_value(float(value))
    if isinstance(value, _datetime.datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, _datetime.date):
        return value.isoformat()
    if isinstance(value, _datetime.time):
        return value.isoformat()
    if isinstance(value, _datetime.timedelta):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, str):
        # Text cells go through the same coercion ladder as CSV cells so that
        # a workbook and its CSV equivalent produce identical datasets.
        return coerce(value)
    return str(value)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_sheet(grid: Sequence[Sequence[Any]]) -> Tuple[List[str], List[List[Any]]]:
    """Turn a rectangular-ish sheet into a header plus data rows."""
    rows = [list(row) for row in grid]
    rows = [row for row in rows if any(not _is_blank(cell) for cell in row)]
    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: the first worksheet requires a header row "
            "and at least one data row."
        )

    width = max(len(row) for row in rows)
    rows = [row + [None] * (width - len(row)) for row in rows]

    # Trailing columns that are empty in every row are padding, not data.
    while width > 1 and all(_is_blank(row[width - 1]) for row in rows):
        width -= 1
    rows = [row[:width] for row in rows]

    header = ["" if cell is None else str(cell).strip() for cell in rows[0]]
    if not any(header):
        raise BadRequest("Non-tabular content: the header row is empty.")

    data = [[_cell_value(cell) for cell in row] for row in rows[1:]]
    if not data:
        raise BadRequest(
            "Non-tabular content: the first worksheet requires a header row "
            "and at least one data row."
        )
    return header, data


def _xlsx_grid(raw: bytes, data_only: bool) -> List[List[Any]]:
    """The cell grid of the first worksheet of an OOXML workbook."""
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=data_only)
    except DataGateError:
        raise
    except Exception as exc:
        raise BadRequest("Unrecognized format: %s" % _brief(exc)) from None

    try:
        sheets = workbook.worksheets
        if not sheets:
            raise BadRequest("Non-tabular content: the workbook has no sheets.")
        return [list(row) for row in sheets[0].iter_rows(values_only=True)]
    except DataGateError:
        raise
    except Exception as exc:
        raise BadRequest("Unrecognized format: %s" % _brief(exc)) from None
    finally:
        try:
            workbook.close()
        except Exception:
            pass


def read_xlsx(raw: bytes) -> Tuple[List[str], List[List[Any]]]:
    """Read the first worksheet of an OOXML workbook.

    Cached formula results are preferred. A workbook saved without them
    would otherwise look empty, so such a sheet is re-read with the formula
    text in place of the values it never carried.
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:  # pragma: no cover - dependency is declared
        raise BadRequest(
            "Unrecognized format: .xlsx support requires the 'openpyxl' "
            "package."
        ) from None

    try:
        return normalize_sheet(_xlsx_grid(raw, data_only=True))
    except BadRequest:
        return normalize_sheet(_xlsx_grid(raw, data_only=False))


def _xls_cell(book: Any, cell: Any) -> Any:
    """Convert one xlrd cell into a plain Python value."""
    import xlrd

    kind, value = cell.ctype, cell.value
    if kind == xlrd.XL_CELL_EMPTY or kind == xlrd.XL_CELL_BLANK:
        return None
    if kind == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    if kind == xlrd.XL_CELL_ERROR:
        return ""
    if kind == xlrd.XL_CELL_DATE:
        try:
            parts = xlrd.xldate_as_tuple(value, book.datemode)
        except Exception:
            return value
        year, month, day, hour, minute, second = parts
        if (year, month, day) == (0, 0, 0):
            return _datetime.time(hour, minute, second).isoformat()
        return _datetime.datetime(year, month, day, hour, minute, second)
    return value


def read_xls(raw: bytes) -> Tuple[List[str], List[List[Any]]]:
    """Read the first worksheet of a legacy BIFF workbook."""
    try:
        import xlrd
    except ImportError:  # pragma: no cover - dependency is declared
        raise BadRequest(
            "Unrecognized format: .xls support requires the 'xlrd' package."
        ) from None

    try:
        book = xlrd.open_workbook(file_contents=raw, on_demand=False)
    except DataGateError:
        raise
    except Exception as exc:
        raise BadRequest("Unrecognized format: %s" % _brief(exc)) from None

    try:
        if book.nsheets < 1:
            raise BadRequest("Non-tabular content: the workbook has no sheets.")
        sheet = book.sheet_by_index(0)
        grid = [
            [_xls_cell(book, cell) for cell in sheet.row(index)]
            for index in range(sheet.nrows)
        ]
    except DataGateError:
        raise
    except Exception as exc:
        raise BadRequest("Unrecognized format: %s" % _brief(exc)) from None
    finally:
        try:
            book.release_resources()
        except Exception:
            pass

    return normalize_sheet(grid)


def ingest_source(
    raw: bytes, charset_param: Optional[str]
) -> Tuple[List[str], List[List[Any]], str]:
    """Turn raw source bytes into a header, typed data rows and their format.

    `charset` only ever applies to text CSV sources; a workbook carries its
    own encoding, so the parameter is neither used nor validated for one.

    The detected format is handed back alongside the data because enrichment
    describes the source the rows came from, and detection is content-driven:
    re-deriving it later would mean sniffing the same bytes twice.
    """
    kind = detect_format(raw)
    if kind == FORMAT_XLSX:
        columns, rows = read_xlsx(raw)
        return columns, rows, kind
    if kind == FORMAT_XLS:
        columns, rows = read_xls(raw)
        return columns, rows, kind

    charset = validate_charset(charset_param)
    text = decode_bytes(raw, charset)
    columns, rows = parse_tabular(raw, text)
    return columns, [[coerce(cell) for cell in row] for row in rows], kind


def ingest(raw: bytes, charset_param: Optional[str]) -> Tuple[List[str], List[List[Any]]]:
    """`ingest_source` for callers that have no use for the source format."""
    columns, rows, _kind = ingest_source(raw, charset_param)
    return columns, rows


# --------------------------------------------------------------------------
# Dataset enrichment
# --------------------------------------------------------------------------


def _is_missing(value: Any) -> bool:
    """True for a cell that holds no value.

    A CSV has no null, so "missing" is an empty field: absent, or blank once
    trimmed. A zero or an empty-looking number is a value like any other.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _value_type(value: Any) -> str:
    """The type label of one present cell.

    Booleans are deliberately not numbers here: they only ever reach a
    dataset from a spreadsheet, where they read as labels rather than as
    quantities to compare or total.
    """
    if isinstance(value, bool):
        return TYPE_TEXT
    if isinstance(value, int):
        return TYPE_INTEGER
    if isinstance(value, float):
        return TYPE_FLOAT
    return TYPE_TEXT


def _column_type(kinds: Sequence[str]) -> str:
    """Reduce the per-cell types of one column to a single label.

    Whole numbers make an `integer` column and decimals a `float` one; a
    column holding both is still numeric, so it is the broader `number`. One
    piece of text is enough to make the whole column `text`, and a column
    with nothing in it at all is `text` rather than a guess at what it would
    have held.
    """
    seen = set(kinds)
    if not seen or TYPE_TEXT in seen:
        return TYPE_TEXT
    if seen == {TYPE_INTEGER}:
        return TYPE_INTEGER
    if seen == {TYPE_FLOAT}:
        return TYPE_FLOAT
    return TYPE_NUMBER


def _distinct_key(value: Any) -> Tuple[str, Any]:
    """A hashable identity for one cell, used to count distinct values.

    The type label is part of the key because Python considers `1` and `1.0`
    the same set member while a dataset does not: they are two different
    values that happen to compare equal.
    """
    return (_value_type(value), value)


def column_detail(values: Iterable[Any]) -> Dict[str, Any]:
    """Describe one column: its type, and how full and how varied it is.

    Missing cells are counted on their own and are excluded from both the
    type and the distinct count, so a column does not become `text` -- nor
    gain a value it never held -- because some of its rows are empty.
    """
    distinct = set()
    kinds = set()
    missing = 0
    for value in values:
        if _is_missing(value):
            missing += 1
            continue
        kinds.add(_value_type(value))
        distinct.add(_distinct_key(value))
    return {
        "type": _column_type(kinds),
        "distinct_count": len(distinct),
        "missing_count": missing,
    }


def build_metadata(
    kind: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> Dict[str, Any]:
    """The enrichment metadata of one freshly ingested dataset.

    Every dataset gets a summary of the source it came from. Per-column
    detail is a property of parsed text: a workbook's own cell types already
    survive ingestion, so only CSV sources are profiled column by column.
    """
    summary = {
        "filetype": FILETYPE_EXCEL if kind in (FORMAT_XLSX, FORMAT_XLS) else FILETYPE_CSV,
        "row_count": len(rows),
        "column_count": len(columns),
    }
    metadata: Dict[str, Any] = {"dataset_summary": summary}
    if summary["filetype"] == FILETYPE_CSV:
        details: Dict[str, Any] = {}
        for index, name in enumerate(columns):
            # A duplicated header name keeps the first column it labels: the
            # details are keyed by name, and that is the column a filter or a
            # sort on that name reaches too.
            if name in details:
                continue
            details[name] = column_detail(
                row[index] if index < len(row) else None for row in rows
            )
        metadata["column_details"] = details
    return metadata


# --------------------------------------------------------------------------
# CSV export
# --------------------------------------------------------------------------


def export_cell(value: Any) -> str:
    """Render one dataset value back into a CSV field."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if value.is_integer() and abs(value) < 2 ** 53:
            return str(int(value))
        return repr(value)
    if isinstance(value, str):
        return value
    return str(value)


def render_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    """Serialise a header and rows as RFC 4180 CSV."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer, lineterminator=EXPORT_NEWLINE, quoting=csv.QUOTE_MINIMAL
    )
    writer.writerow([export_cell(name) for name in columns])
    for row in rows:
        writer.writerow([export_cell(cell) for cell in row])
    return buffer.getvalue().encode("utf-8")


# --------------------------------------------------------------------------
# Flask application
# --------------------------------------------------------------------------


def create_app(
    cache_enabled: Optional[bool] = None, config: Optional[Config] = None
) -> Flask:
    if config is None:
        config = load_config()
    if cache_enabled is None:
        cache_enabled = config.cache_enabled
    else:
        config.cache_enabled = cache_enabled

    # Datasets are read back from -- and written to -- the storage directory,
    # so the ones a previous run ingested are queryable straight away.
    STORE.configure(config.storage_dir)

    app = Flask(__name__)
    app.config["CACHE_ENABLED"] = cache_enabled
    app.config["DATAGATE"] = config
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    # Werkzeug caps non-file multipart fields at 500 kB by default, which
    # would reject a perfectly ordinary CSV sent without a file name.
    app.config["MAX_CONTENT_LENGTH"] = None
    app.config["MAX_FORM_MEMORY_SIZE"] = MAX_UPLOAD_BYTES
    app.config["MAX_FORM_PARTS"] = 1000

    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        methods=["GET", "HEAD", "OPTIONS", "POST"],
        allow_headers="*",
        expose_headers="*",
        max_age=86400,
    )

    def ok(payload: Dict[str, Any], status: int = 200):
        body = {"ok": True}
        body.update(payload)
        return _json_response(body, status)

    def fail(message: str, status: int):
        return _json_response({"ok": False, "error": message}, status)

    def _json_response(body: Dict[str, Any], status: int):
        response = app.response_class(
            response=json.dumps(body, ensure_ascii=False, allow_nan=False) + "\n",
            status=status,
            mimetype="application/json",
        )
        _apply_cors(response)
        return response

    def endpoint_url(dataset_id: str) -> str:
        """The dataset endpoint handed back by /convert and /upload.

        Relative by default; with `REQUIRE_TLS` the same path is returned as
        an absolute `https://` URL built from the host of the request, so a
        caller behind a TLS terminator never follows it back over plain HTTP.
        """
        path = "/datasets/%s" % dataset_id
        if not config.require_tls:
            return path
        return "https://%s%s" % (request.host, path)

    def cached_convert(dataset_id: str):
        """The /convert answer for a source that is already stored.

        The size limit is checked against the size recorded with the parse, so
        a limit lowered since then still refuses the source instead of handing
        back a dataset that is now too big to have been accepted.
        """
        record = STORE.get(dataset_id) or {}
        size = record.get("size")
        if isinstance(size, int):
            check_source_size(size, config.max_source_size, "Source")
        return ok({"endpoint": endpoint_url(dataset_id)})

    def _apply_cors(response) -> None:
        headers = response.headers
        headers.setdefault("Access-Control-Allow-Origin", "*")
        headers.setdefault(
            "Access-Control-Allow-Methods", "GET, HEAD, OPTIONS, POST"
        )
        headers.setdefault("Access-Control-Allow-Headers", "*")
        headers.setdefault("Access-Control-Expose-Headers", "*")
        headers.setdefault("Access-Control-Max-Age", "86400")

    # -- access control --------------------------------------------------

    @app.before_request
    def _enforce_origin_allowlist():
        """Refuse anything that does not come from an allowed origin.

        Runs before routing, so a request from somewhere else is turned away
        whatever it asked for -- including paths that do not exist.
        """
        if not config.origin_allowlist:
            return None
        referer = request.headers.get(REFERER_HEADER)
        if referer is None or not referer.strip():
            return fail(
                "Missing %s header: this service only serves requests from "
                "an allowed origin." % REFERER_HEADER,
                403,
            )
        hostname = referer_hostname(referer)
        if hostname is None:
            return fail(
                "Malformed %s header %r: no host to check against the origin "
                "allowlist." % (REFERER_HEADER, referer),
                403,
            )
        if not host_allowed(hostname, config.origin_allowlist):
            return fail("Origin %r is not allowed." % hostname, 403)
        return None

    # -- routes ----------------------------------------------------------

    @app.route("/convert", methods=["GET", "HEAD", "OPTIONS"])
    def convert():
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)

        # The request is validated before the cache is consulted, so a
        # malformed request is rejected whether or not its source is cached.
        try:
            source = validate_source(request.args.get("source"))
            forced = parse_force(request.args)
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        enrich = parse_enrich(request.args)
        charset_param = request.args.get("charset")
        dataset_id = STORE.make_id(source)
        key = cache_key(source, charset_param)
        # `force` and a disabled cache both mean "ingest now"; neither drops
        # the stored dataset up front, so a failure below changes nothing.
        use_cache = cache_enabled and not forced

        def servable() -> bool:
            """True when the stored dataset already answers this request.

            Enrichment is not part of the cache key -- the bytes and the way
            they are decoded are -- so it is checked separately: an enriched
            request needs an enriched dataset, while a plain one is happy
            with either and leaves an enriched dataset exactly as it is.
            """
            if not STORE.cached(dataset_id, key):
                return False
            return STORE.enriched(dataset_id) if enrich else True

        try:
            if use_cache and servable():
                return cached_convert(dataset_id)

            with STORE.ingest_lock(dataset_id):
                # A concurrent request for the same source may have filled the
                # cache while this one waited for the lock.
                if use_cache and servable():
                    return cached_convert(dataset_id)
                raw = fetch_source(source, config.max_source_size)
                check_source_size(len(raw), config.max_source_size, "Source")
                columns, rows, kind = ingest_source(raw, charset_param)
                # Metadata is computed from the bytes just fetched and before
                # anything is stored, so a dataset is never written down as
                # non-enriched because describing it went wrong.
                metadata = enrich_metadata(kind, columns, rows) if enrich else None
                _store_dataset(
                    dataset_id, source, columns, rows, key, len(raw), metadata
                )
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        return ok({"endpoint": endpoint_url(dataset_id)})

    @app.route("/upload", methods=["POST", "OPTIONS"])
    def upload():
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        try:
            raw = read_upload(request)
            check_source_size(
                len(raw), config.max_source_size, "Uploaded file"
            )
            columns, rows = ingest(raw, upload_charset(request))
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        # `enrich` is a /convert parameter: an upload has no source to
        # re-read, so it is stored plainly whatever the query string says.
        dataset_id = STORE.make_content_id(raw)
        _store_dataset(
            dataset_id, "upload:%s" % dataset_id, columns, rows, None, len(raw)
        )
        return ok({"endpoint": endpoint_url(dataset_id)})

    @app.route("/datasets/<dataset_id>", methods=["GET", "HEAD", "OPTIONS"])
    def dataset(dataset_id: str):
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        started = time.perf_counter()
        record = STORE.get(dataset_id)
        if record is None:
            return fail("Unknown dataset id: %r." % dataset_id, 404)

        try:
            columns, controls, total, window = run_query(
                record, request.args, started
            )
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        rows: List[Any]
        if controls.shape == "objects":
            rows = [
                _as_object(rowid, row, columns, controls.hide_rowid)
                for rowid, row in window
            ]
        else:
            rows = [list(row) for _rowid, row in window]

        payload: Dict[str, Any] = {"columns": columns}
        if not controls.hide_total:
            payload["total"] = total
        payload["rows"] = rows
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        payload["query_ms"] = round(elapsed_ms, 4)
        # Metadata describes the whole stored dataset, not this window of it,
        # so it is attached unchanged by filters, sorting and pagination. A
        # dataset ingested without enrichment has none, and the fields are
        # then left out rather than reported as empty.
        if record.get("enriched"):
            summary = record.get("dataset_summary")
            if isinstance(summary, dict):
                payload["dataset_summary"] = dict(summary)
            details = record.get("column_details")
            if isinstance(details, dict):
                payload["column_details"] = {
                    name: dict(detail) if isinstance(detail, dict) else detail
                    for name, detail in details.items()
                }
        return ok(payload)

    @app.route("/datasets/<dataset_id>/export", methods=["GET", "HEAD", "OPTIONS"])
    def export(dataset_id: str):
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        started = time.perf_counter()
        record = STORE.get(dataset_id)
        if record is None:
            return fail("Unknown dataset id: %r." % dataset_id, 404)

        try:
            # `_shape`, `_rowid` and `_total` are still validated, but a CSV
            # rendering has no place to honour them.
            columns, _controls, _total, window = run_query(
                record, request.args, started
            )
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        body = render_csv(columns, (row for _rowid, row in window))
        response = app.response_class(
            response=body, status=200, mimetype=EXPORT_MIMETYPE
        )
        response.headers["Content-Type"] = EXPORT_MIMETYPE
        response.headers["Content-Disposition"] = (
            'attachment; filename="%s.csv"' % dataset_id
        )
        _apply_cors(response)
        return response

    @app.route("/", methods=["GET", "HEAD", "OPTIONS"])
    def index():
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        return ok(
            {
                "service": "datagate",
                "endpoints": [
                    "/convert?source=<url>[&charset=<name>][&force]"
                    "[&enrich=yes]",
                    "POST /upload[?charset=<name>] (multipart field 'file' "
                    "or 'attachment')",
                    "/datasets/<id>[?_size=&_offset=&_sort=&_sort_desc="
                    "&_shape=&_rowid=hide&_total=hide]"
                    "[&<column>__<exact|contains|less|greater>=<value>]",
                    "/datasets/<id>/export[?<same query as /datasets/<id>>]",
                ],
            }
        )

    # -- error handling --------------------------------------------------

    @app.errorhandler(400)
    def _bad_request(exc):
        return fail(_describe(exc, "Bad request."), 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return fail(_describe(exc, "Not found."), 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return fail(_describe(exc, "Method not allowed."), 405)

    @app.errorhandler(413)
    def _too_large(exc):
        return fail(_describe(exc, "Request body too large."), 413)

    @app.errorhandler(415)
    def _unsupported_media(exc):
        return fail(_describe(exc, "Unsupported media type."), 415)

    @app.errorhandler(DataGateError)
    def _datagate_error(exc: DataGateError):
        return fail(exc.message, exc.status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, DataGateError):
            return fail(exc.message, exc.status)
        status = getattr(exc, "code", None)
        if isinstance(status, int):
            return fail(_describe(exc, "Request failed."), status)
        app.logger.exception("Unhandled error")
        return fail("Internal server error: %s" % _brief(exc), 500)

    @app.after_request
    def _after(response):
        _apply_cors(response)
        return response

    return app


def _as_object(
    rowid: int, row: List[Any], columns: List[str], hide_rowid: bool
) -> Dict[str, Any]:
    """Render one row as an object, with `rowid` leading unless hidden."""
    obj: Dict[str, Any] = {}
    if not hide_rowid:
        obj["rowid"] = rowid
    for name, value in zip(columns, row):
        obj[name] = value
    return obj


def _describe(exc: Any, default: str) -> str:
    description = getattr(exc, "description", None)
    if isinstance(description, str) and description.strip():
        return description
    return default


def _store_dataset(
    dataset_id: str,
    source: str,
    columns: List[str],
    rows: List[List[Any]],
    key: Any = None,
    size: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Register one parsed dataset under a deterministic id.

    Storing only ever happens after a successful parse -- and after any
    metadata it was asked for has been computed -- so a failed (or forced and
    then failed) re-ingestion leaves the previous dataset queryable, still
    enriched if that is how it was stored.
    """
    payload: Dict[str, Any] = {
        "source": source,
        "size": size,
        "columns": list(columns),
        "rows": rows,
        "rowids": list(range(FIRST_DATA_ROWID, FIRST_DATA_ROWID + len(rows))),
        "cache_key": key,
        "enriched": metadata is not None,
        "dataset_summary": None,
        "column_details": None,
    }
    if metadata is not None:
        payload.update(metadata)
    STORE.put(dataset_id, payload)


def enrich_metadata(
    kind: str, columns: List[str], rows: List[List[Any]]
) -> Dict[str, Any]:
    """`build_metadata`, with any failure turned into a JSON error.

    Describing a dataset must not be able to take the service down, and it
    must not quietly fall back to storing the dataset unenriched either: the
    caller asked for enrichment, so a request that cannot deliver it fails
    and leaves whatever was already stored untouched.
    """
    try:
        return build_metadata(kind, columns, rows)
    except DataGateError:
        raise
    except Exception as exc:
        raise DataGateError(
            "Enrichment failed: %s" % _brief(exc), 500
        ) from None


def run_query(
    record: Dict[str, Any], args: Any, started: float
) -> Tuple[List[str], "Controls", int, List[Tuple[int, List[Any]]]]:
    """Apply controls and filters to a stored dataset.

    Shared by `/datasets/<id>` and `/datasets/<id>/export` so that both see
    exactly the same filter -> sort -> paginate pipeline.
    """
    columns = list(record["columns"])
    deadline = Deadline(started + QUERY_TIMEOUT)
    controls = parse_controls(args, columns)
    filters = parse_filters(args, columns)

    # Filter, then sort the survivors, then page through the result.
    ordered = apply_filters(zip(record["rowids"], record["rows"]), filters, deadline)
    if controls.sort_index is not None:
        # `list.sort` is stable both ways, so ties keep source order.
        ordered.sort(
            key=deadline_sort_key(deadline, controls.sort_index),
            reverse=controls.sort_desc,
        )
        deadline.check_now()

    total = len(ordered)
    window = ordered[controls.offset : controls.offset + controls.size]
    return columns, controls, total, window


# --------------------------------------------------------------------------
# Upload handling
# --------------------------------------------------------------------------


def upload_charset(req: Any) -> Optional[str]:
    """The `charset` of an upload: a query parameter, or a form field."""
    raw = req.args.get("charset")
    if raw is not None:
        return raw
    try:
        return req.form.get("charset")
    except Exception:
        return None


def _multipart_parts(req: Any) -> Tuple[Any, Any]:
    """Parse the multipart body, mapping every parser failure onto 400."""
    try:
        return req.files, req.form
    except DataGateError:
        raise
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status == 413:
            raise DataGateError("Uploaded file is too large.", 413) from None
        raise BadRequest("Malformed multipart body: %s" % _brief(exc)) from None


_PART_NAME_RE = re.compile(
    rb'name\s*=\s*"((?:[^"\\]|\\.)*)"|name\s*=\s*([^;\r\n]+)', re.IGNORECASE
)


def _raw_part(body: bytes, boundary: str, field: str) -> Optional[bytes]:
    """The verbatim payload of one multipart part, found by field name.

    A part sent without a file name is decoded as text by the form parser,
    which is lossy for anything that is not UTF-8. Uploads are bytes, so the
    payload is recovered from the untouched body instead.
    """
    if not boundary:
        return None
    wanted = field.encode("utf-8")
    for chunk in body.split(b"--" + boundary.encode("latin-1")):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        head, separator, payload = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        for line in head.split(b"\r\n"):
            if not line.lower().startswith(b"content-disposition:"):
                continue
            match = _PART_NAME_RE.search(line)
            if match and (match.group(1) or match.group(2) or b"").strip() == wanted:
                if payload.endswith(b"\r\n"):
                    payload = payload[:-2]
                return payload
    return None


def read_upload(req: Any) -> bytes:
    """Return the bytes of the uploaded `file` / `attachment` part."""
    if (req.mimetype or "").lower() != MULTIPART_MIMETYPE:
        raise UnsupportedMediaType(
            "Uploads must be sent as '%s', got %r."
            % (MULTIPART_MIMETYPE, req.content_type or "")
        )

    # Cache the body before the form parser consumes it; the parser reads the
    # cached copy, and the raw bytes stay available for `_raw_part`.
    try:
        body = req.get_data(cache=True, parse_form_data=False)
    except Exception as exc:
        raise BadRequest("Malformed multipart body: %s" % _brief(exc)) from None

    files, form = _multipart_parts(req)

    for field in UPLOAD_FIELDS:
        storage = files.get(field)
        if storage is not None:
            try:
                data = storage.read()
            except Exception as exc:
                raise BadRequest(
                    "Malformed multipart body: %s" % _brief(exc)
                ) from None
            return data if isinstance(data, bytes) else bytes(data)

    # A part sent without a file name arrives as an ordinary form value.
    for field in UPLOAD_FIELDS:
        if field not in form:
            continue
        exact = _raw_part(body, req.mimetype_params.get("boundary", ""), field)
        if exact is not None:
            return exact
        return form[field].encode("utf-8", "surrogateescape")

    raise BadRequest(
        "Malformed or incomplete multipart body: expected a %s part."
        % " or ".join("'%s'" % name for name in UPLOAD_FIELDS)
    )


# --------------------------------------------------------------------------
# Control parameters
# --------------------------------------------------------------------------

# ASCII digits only: `int()` would happily accept other Unicode digit forms.
_UNSIGNED_INT_RE = re.compile(r"\+?[0-9]+")


class Controls:
    """The validated pagination / sorting / shape controls of one request."""

    __slots__ = (
        "size",
        "offset",
        "shape",
        "sort_index",
        "sort_desc",
        "hide_rowid",
        "hide_total",
    )

    def __init__(
        self,
        size: int = DEFAULT_ROW_LIMIT,
        offset: int = 0,
        shape: str = "lists",
        sort_index: Optional[int] = None,
        sort_desc: bool = False,
        hide_rowid: bool = False,
        hide_total: bool = False,
    ) -> None:
        self.size = size
        self.offset = offset
        self.shape = shape
        self.sort_index = sort_index
        self.sort_desc = sort_desc
        self.hide_rowid = hide_rowid
        self.hide_total = hide_total


def _reject_repeats(args: Any) -> None:
    """A control parameter given more than once is always a client error."""
    for name in CONTROL_PARAMS:
        if len(args.getlist(name)) > 1:
            raise BadRequest(
                "Query parameter '%s' must not be repeated." % name
            )


def _parse_unsigned(name: str, raw: Optional[str], minimum: int, default: int) -> int:
    """Parse a base-10 integer that must be >= `minimum`."""
    if raw is None:
        return default
    token = raw.strip()
    wanted = "a positive integer" if minimum > 0 else "a non-negative integer"
    if not _UNSIGNED_INT_RE.fullmatch(token):
        raise BadRequest(
            "Query parameter '%s' must be %s, got %r." % (name, wanted, raw)
        )
    value = int(token)
    if value < minimum:
        raise BadRequest(
            "Query parameter '%s' must be %s, got %r." % (name, wanted, raw)
        )
    return value


def _parse_shape(raw: Optional[str]) -> str:
    if raw is None:
        return SHAPES[0]
    shape = raw.strip()
    if shape not in SHAPES:
        raise BadRequest(
            "Query parameter '_shape' must be one of %s, got %r."
            % (" or ".join("'%s'" % s for s in SHAPES), raw)
        )
    return shape


def _parse_toggle(name: str, raw: Optional[str]) -> bool:
    """`_rowid` / `_total` accept the single value `hide`."""
    if raw is None:
        return False
    if raw.strip() != HIDE:
        raise BadRequest(
            "Query parameter '%s' only accepts the value '%s', got %r."
            % (name, HIDE, raw)
        )
    return True


def _parse_sort_column(name: str, raw: str, columns: List[str]) -> int:
    column = raw.strip()
    if not column:
        raise BadRequest("Query parameter '%s' must name a column." % name)
    try:
        return columns.index(column)
    except ValueError:
        raise BadRequest(
            "Query parameter '%s' names an unknown column: %r." % (name, raw)
        ) from None


def parse_controls(args: Any, columns: List[str]) -> Controls:
    """Validate every control parameter of a /datasets/<id> request."""
    _reject_repeats(args)

    controls = Controls(
        size=_parse_unsigned("_size", args.get("_size"), 1, DEFAULT_ROW_LIMIT),
        offset=_parse_unsigned("_offset", args.get("_offset"), 0, 0),
        shape=_parse_shape(args.get("_shape")),
        hide_rowid=_parse_toggle("_rowid", args.get("_rowid")),
        hide_total=_parse_toggle("_total", args.get("_total")),
    )

    # Both sort parameters are validated even when only one of them is used,
    # then `_sort_desc` wins whenever the two are given together.
    ascending = args.get("_sort")
    descending = args.get("_sort_desc")
    if ascending is not None:
        controls.sort_index = _parse_sort_column("_sort", ascending, columns)
        controls.sort_desc = False
    if descending is not None:
        controls.sort_index = _parse_sort_column("_sort_desc", descending, columns)
        controls.sort_desc = True
    return controls


def sort_key(value: Any) -> Tuple[int, float, str]:
    """Total order across the mixed JSON types a column may hold.

    Numbers sort together ahead of text so that comparisons never depend on
    types Python refuses to order against each other.
    """
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, str(value))


# --------------------------------------------------------------------------
# Column filters
# --------------------------------------------------------------------------

# ASCII decimals only, mirroring the strictness of the control parsers: this is
# what "numeric" means on both sides of a `__less` / `__greater` comparison.
_NUMERIC_RE = re.compile(
    r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?"
)


def _as_text(value: Any) -> str:
    """The text a cell compares as, matching how it is rendered in JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _as_number(value: Any) -> Optional[float]:
    """The float a cell compares as, or None when the cell is not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not _NUMERIC_RE.fullmatch(token):
        return None
    try:
        return float(token)
    except (ValueError, OverflowError):
        return None


class Filter:
    """One validated `<column>__<comparator>=<value>` query parameter."""

    __slots__ = ("key", "column", "index", "comparator", "value", "number")

    def __init__(
        self,
        key: str,
        column: str,
        index: int,
        comparator: str,
        value: str,
        number: Optional[float] = None,
    ) -> None:
        self.key = key
        self.column = column
        self.index = index
        self.comparator = comparator
        self.value = value
        self.number = number

    def matches(self, cell: Any) -> bool:
        if self.comparator == "exact":
            return _as_text(cell) == self.value
        if self.comparator == "contains":
            return self.value in _as_text(cell)
        number = _as_number(cell)
        if number is None:
            return False  # a non-numeric cell never matches a numeric compare
        if self.comparator == "less":
            return number < self.number
        return number > self.number


def _filter_splits(key: str) -> List[Tuple[str, str]]:
    """Every `column`/`comparator` split of a filter key, longest column first.

    Splitting from the right lets a column whose own name contains the
    separator -- `first__name__exact` -- still resolve to that column.
    """
    splits: List[Tuple[str, str]] = []
    at = len(key)
    while True:
        at = key.rfind(FILTER_SEPARATOR, 0, at)
        if at < 0:
            return splits
        splits.append((key[:at], key[at + len(FILTER_SEPARATOR) :]))


def _split_filter_key(key: str, columns: List[str]) -> Tuple[str, str]:
    """Resolve a filter key into a known column and a supported comparator."""
    supported = [pair for pair in _filter_splits(key) if pair[1] in COMPARATORS]
    if not supported:
        raise BadRequest(
            "Filter '%s' uses an unsupported comparator: expected one of %s."
            % (key, ", ".join("'%s'" % name for name in COMPARATORS))
        )
    for column, comparator in supported:
        if column in columns:
            return column, comparator
    raise BadRequest(
        "Filter '%s' names an unknown column: %r." % (key, supported[0][0])
    )


def _filter_number(key: str, raw: str) -> float:
    """Parse the value of a `__less` / `__greater` filter."""
    token = raw.strip()
    if _NUMERIC_RE.fullmatch(token):
        try:
            return float(token)
        except (ValueError, OverflowError):
            pass
    raise BadRequest(
        "Filter '%s' requires a numeric value, got %r." % (key, raw)
    )


def parse_filters(args: Any, columns: List[str]) -> List[Filter]:
    """Validate every filter parameter of a /datasets/<id> request."""
    filters: List[Filter] = []
    for key, values in args.lists():
        if key.startswith("_") or FILTER_SEPARATOR not in key:
            continue  # a control parameter, or not a filter at all
        if len(values) > 1:
            raise BadRequest("Filter '%s' must not be repeated." % key)
        column, comparator = _split_filter_key(key, columns)
        raw = values[0]
        filters.append(
            Filter(
                key,
                column,
                columns.index(column),
                comparator,
                raw,
                _filter_number(key, raw)
                if comparator in NUMERIC_COMPARATORS
                else None,
            )
        )
    return filters


def apply_filters(
    rows: Any, filters: List[Filter], deadline: "Deadline"
) -> List[Tuple[int, List[Any]]]:
    """Keep the rows matching every filter, in source order."""
    if not filters:
        deadline.check_now()
        return list(rows)
    kept: List[Tuple[int, List[Any]]] = []
    for rowid, row in rows:
        deadline.check()
        if all(rule.matches(row[rule.index]) for rule in filters):
            kept.append((rowid, row))
    deadline.check_now()
    return kept


# --------------------------------------------------------------------------
# Query budget
# --------------------------------------------------------------------------

# Rows evaluated between two readings of the clock.
_DEADLINE_STRIDE = 512


class Deadline:
    """The wall-clock budget of one query, checked without a clock call per row."""

    __slots__ = ("expires", "_countdown")

    def __init__(self, expires: float) -> None:
        self.expires = expires
        self._countdown = _DEADLINE_STRIDE

    def check(self) -> None:
        """Check the budget once every `_DEADLINE_STRIDE` calls."""
        self._countdown -= 1
        if self._countdown <= 0:
            self.check_now()

    def check_now(self) -> None:
        self._countdown = _DEADLINE_STRIDE
        if time.perf_counter() > self.expires:
            raise BadRequest(
                "Query timed out after %g seconds." % QUERY_TIMEOUT
            )


def deadline_sort_key(deadline: Deadline, index: int) -> Any:
    """`sort_key` for one column, with the query budget checked as it runs."""

    def key(pair: Tuple[int, List[Any]]) -> Tuple[int, float, str]:
        deadline.check()
        return sort_key(pair[1][index])

    return key


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datagate",
        description="Convert remote CSV files into queryable JSON datasets.",
    )
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="Start the datagate HTTP server.")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", type=str, default=DEFAULT_ADDRESS)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.command != "start":
        parser.print_help()
        return 1

    # Bad configuration stops the server before it binds a port, so nobody
    # can talk to a datagate whose limits and access rules are undefined.
    try:
        config = load_config()
        app = create_app(config=config)
    except ConfigError as exc:
        print("datagate: %s" % exc, file=sys.stderr)
        return 2
    app.run(
        host=args.address,
        port=args.port,
        threaded=True,
        debug=False,
        use_reloader=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

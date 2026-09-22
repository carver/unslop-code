#!/usr/bin/env python3
"""datagate -- turn remote CSV and spreadsheet files into queryable JSON datasets.

Usage:
    python datagate.py start --port 8001 --address 127.0.0.1
"""

from __future__ import annotations

import argparse
import codecs
import csv
import datetime
import hashlib
import io
import json
import math
import os
import re
import sys
import threading
import time
import zipfile
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.formparser import FormDataParser

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_ROW_LIMIT = 100
# Settings come from built-in defaults, then the DATAGATE_CONFIG file, then the
# environment directly; a later source always wins over an earlier one.
CONFIG_ENV_VAR = "DATAGATE_CONFIG"
CACHE_ENV_VAR = "CACHE_ENABLED"
MAX_SOURCE_SIZE_VAR = "MAX_SOURCE_SIZE"
ORIGIN_ALLOWLIST_VAR = "ORIGIN_ALLOWLIST"
REQUIRE_TLS_VAR = "REQUIRE_TLS"
STORAGE_DIR_VAR = "STORAGE_DIR"
SETTING_NAMES = (
    MAX_SOURCE_SIZE_VAR,
    ORIGIN_ALLOWLIST_VAR,
    REQUIRE_TLS_VAR,
    STORAGE_DIR_VAR,
    CACHE_ENV_VAR,
)
# booleans accept only these spellings, trimmed and compared
# case-insensitively; anything else refuses to start.
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")
CACHE_ENABLED_DEFAULT = True
REQUIRE_TLS_DEFAULT = False
# list settings are comma separated
LIST_SEPARATOR = ","
# config file lines that start with one of these are comments
COMMENT_PREFIXES = ("#", ";")
# where datasets live when STORAGE_DIR is not configured: next to the service,
# so the same install keeps its datasets across restarts wherever it is run from
DEFAULT_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".datagate-storage"
)
# the presence flag that bypasses the cache for a single /convert request
FORCE_PARAM = "force"
# /convert only: exactly "enrich=yes" asks ingestion to profile the dataset
ENRICH_PARAM = "enrich"
ENRICH_ENABLED_VALUE = "yes"
# the filetype labels a dataset summary reports
CSV_FILETYPE = "csv"
EXCEL_FILETYPE = "excel"
# the column type labels an enriched dataset reports
TYPE_TEXT = "text"
TYPE_NUMBER = "number"
TYPE_INTEGER = "integer"
TYPE_FLOAT = "float"
CONTROL_PARAMS = (
    "_size",
    "_offset",
    "_shape",
    "_sort",
    "_sort_desc",
    "_rowid",
    "_total",
    "_timeout_ms",
)
SHAPES = ("lists", "objects")
COMPARATORS = ("exact", "contains", "less", "greater")
NUMERIC_COMPARATORS = ("less", "greater")
# "<column>__<comparator>=<value>"; the column may itself contain the separator,
# so the *last* occurrence is the one that introduces the comparator.
FILTER_SEPARATOR = "__"
DEFAULT_QUERY_TIMEOUT_MS = 5000
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT = 30
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
# multipart field names an upload may use for its payload, in priority order
UPLOAD_FIELDS = ("file", "attachment")
MULTIPART_MIMETYPE = "multipart/form-data"
# the "compound file" magic an Excel 97-2003 (.xls) workbook is wrapped in
OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# a bare BIFF stream (older .xls) instead opens with its BOF record
BIFF_SIGNATURES = (b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08")
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

app = Flask(__name__)
app.url_map.strict_slashes = False

# id -> {"source": str, "columns": [...], "rows": [[...], ...]}
_DATASETS: dict[str, dict] = {}
# (source, charset) -> dataset id, so a repeated /convert can skip the download
_CACHE: dict[tuple, str] = {}
_LOCK = threading.Lock()

# a stored dataset is a file named after its id, so an id may not wander out of
# the storage directory
DATASET_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ConfigError(Exception):
    """A startup configuration value the server refuses to run with."""


class DataGateError(Exception):
    """An error that maps onto a JSON error response."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# startup configuration
# --------------------------------------------------------------------------


class Config:
    """The settings the service runs with, already parsed and validated."""

    def __init__(
        self,
        max_source_size=None,
        origin_allowlist=(),
        require_tls: bool = REQUIRE_TLS_DEFAULT,
        storage_dir: str = DEFAULT_STORAGE_DIR,
        cache_enabled: bool = CACHE_ENABLED_DEFAULT,
    ):
        # None means "no maximum" rather than "zero bytes"
        self.max_source_size = max_source_size
        # an empty allowlist means every request passes
        self.origin_allowlist = tuple(origin_allowlist)
        self.require_tls = require_tls
        self.storage_dir = storage_dir
        self.cache_enabled = cache_enabled


def parse_bool_setting(name: str, raw: str) -> bool:
    """Read a strict boolean setting.

    Values are trimmed and compared case-insensitively; anything that is not one
    of the documented spellings is a startup error rather than a silently
    guessed value.
    """
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigError(
        "invalid %s: %r is not one of %s"
        % (name, raw, ", ".join(TRUE_VALUES + FALSE_VALUES))
    )


def parse_size_setting(name: str, raw: str):
    """Read a byte count, or ``None`` when the value is empty (no maximum)."""
    value = raw.strip()
    if not value:
        return None
    if not re.match(r"^\+?\d+$", value):
        raise ConfigError(
            "invalid %s: %r is not a non-negative integer number of bytes"
            % (name, raw)
        )
    return int(value)


def parse_list_setting(raw: str) -> tuple:
    """Split a comma separated list, dropping blank entries."""
    return tuple(
        item.strip() for item in raw.split(LIST_SEPARATOR) if item.strip()
    )


def parse_path_setting(raw: str) -> str:
    """Read a directory path; an empty value falls back to the default."""
    value = raw.strip()
    if not value:
        return DEFAULT_STORAGE_DIR
    return os.path.abspath(os.path.expanduser(value))


def read_config_file(path: str) -> dict:
    """Parse a ``KEY=VALUE`` settings file into a mapping of raw strings.

    Blank lines and comments are ignored; anything else has to be a ``KEY=VALUE``
    pair, and a file that cannot be read at all is a startup error rather than a
    silently empty configuration.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ConfigError("cannot read %s file %r: %s" % (CONFIG_ENV_VAR, path, exc))
    except UnicodeDecodeError as exc:
        raise ConfigError(
            "cannot read %s file %r: not utf-8 text (%s)" % (CONFIG_ENV_VAR, path, exc)
        )

    settings = {}
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith(COMMENT_PREFIXES):
            continue
        key, separator, value = entry.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ConfigError(
                "invalid config in %s line %d: expected KEY=VALUE, got %r"
                % (path, number, line)
            )
        settings[key.upper()] = value.strip()
    return settings


def collect_settings(environ) -> dict:
    """Overlay the config file and then the environment onto the defaults."""
    settings = {}
    path = (environ.get(CONFIG_ENV_VAR) or "").strip()
    if path:
        settings.update(read_config_file(path))
    for name in SETTING_NAMES:
        if name in environ:
            settings[name] = environ[name]
    return settings


def resolve_config(environ=None) -> Config:
    """Build the Config for this process, raising ConfigError on bad input."""
    environ = os.environ if environ is None else environ
    settings = collect_settings(environ)

    config = Config()
    if MAX_SOURCE_SIZE_VAR in settings:
        config.max_source_size = parse_size_setting(
            MAX_SOURCE_SIZE_VAR, settings[MAX_SOURCE_SIZE_VAR]
        )
    if ORIGIN_ALLOWLIST_VAR in settings:
        config.origin_allowlist = parse_list_setting(settings[ORIGIN_ALLOWLIST_VAR])
    if REQUIRE_TLS_VAR in settings:
        config.require_tls = parse_bool_setting(
            REQUIRE_TLS_VAR, settings[REQUIRE_TLS_VAR]
        )
    if STORAGE_DIR_VAR in settings:
        config.storage_dir = parse_path_setting(settings[STORAGE_DIR_VAR])
    if CACHE_ENV_VAR in settings:
        config.cache_enabled = parse_bool_setting(
            CACHE_ENV_VAR, settings[CACHE_ENV_VAR]
        )
    return config


def ensure_storage_dir(path: str) -> None:
    """Create the storage directory if it is missing."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError("cannot create %s %r: %s" % (STORAGE_DIR_VAR, path, exc))
    if not os.path.isdir(path):
        raise ConfigError("invalid %s: %r is not a directory" % (STORAGE_DIR_VAR, path))


def configure(environ=None) -> None:
    global CONFIG
    config = resolve_config(environ)
    ensure_storage_dir(config.storage_dir)
    CONFIG = config


CONFIG = Config()

try:
    configure()
except ConfigError as _exc:  # reported with a clean message by main()
    _CONFIG_ERROR = _exc
else:
    _CONFIG_ERROR = None


# --------------------------------------------------------------------------
# response helpers
# --------------------------------------------------------------------------


def ok(payload: dict, status: int = 200):
    body = {"ok": True}
    body.update(payload)
    return jsonify(body), status


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"
    return response


@app.errorhandler(HTTPException)
def handle_http_exception(exc: HTTPException):
    if exc.code == 404:
        message = "not found"
    elif exc.code == 405:
        message = "method not allowed"
    else:
        message = exc.description or exc.name
    return fail(message, exc.code or 500)


@app.errorhandler(DataGateError)
def handle_datagate_error(exc: DataGateError):
    return fail(exc.message, exc.status)


@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):  # pragma: no cover - safety net
    if isinstance(exc, HTTPException):
        return handle_http_exception(exc)
    return fail("internal server error: %s" % exc, 500)


# --------------------------------------------------------------------------
# access control (origin allowlist)
# --------------------------------------------------------------------------


def normalise_domain(domain: str) -> str:
    """Fold a hostname or allowlist entry to its comparable form.

    Matching is case-insensitive, and neither a trailing root dot nor the
    leading ``.``/``*.`` some allowlists spell suffixes with changes which
    domains an entry covers.
    """
    value = domain.strip().lower().rstrip(".")
    if value.startswith("*."):
        value = value[2:]
    return value.lstrip(".")


def host_allowed(host: str, allowlist) -> bool:
    """True when ``host`` is, or sits under, one of the allowed suffixes.

    Suffixes match on domain boundaries: ``example.com`` covers
    ``example.com`` and ``app.example.com`` but never ``notexample.com`` or
    ``example.com.evil.net``.
    """
    candidate = normalise_domain(host)
    if not candidate:
        return False
    for entry in allowlist:
        suffix = normalise_domain(entry)
        if not suffix:
            continue
        if candidate == suffix or candidate.endswith("." + suffix):
            return True
    return False


def referer_host(referer: str):
    """The hostname a Referer points at, or ``None`` when it has none."""
    try:
        parsed = urlparse(referer.strip())
    except ValueError:
        return None
    try:
        host = parsed.hostname
    except ValueError:
        return None
    return host or None


@app.before_request
def enforce_origin_allowlist():
    """Reject disallowed origins before any route gets to run.

    With no allowlist configured every request passes; with one configured a
    request has to carry a Referer whose hostname matches an allowed suffix.
    """
    allowlist = CONFIG.origin_allowlist
    if not allowlist:
        return None

    referer = request.headers.get("Referer")
    if referer is None or not referer.strip():
        raise DataGateError(
            "missing Referer header: this service only serves the configured "
            "origin allowlist",
            403,
        )

    host = referer_host(referer)
    if host is None:
        raise DataGateError(
            "referer not allowed: %s has no hostname" % referer.strip(), 403
        )
    if not host_allowed(host, allowlist):
        raise DataGateError("referer not allowed: %s" % host, 403)
    return None


# --------------------------------------------------------------------------
# size limits
# --------------------------------------------------------------------------


def enforce_source_size(size: int) -> None:
    """Reject a source larger than MAX_SOURCE_SIZE; the limit itself fits."""
    limit = CONFIG.max_source_size
    if limit is not None and size > limit:
        raise DataGateError(
            "source is too large: %d bytes exceeds the %d byte %s limit"
            % (size, limit, MAX_SOURCE_SIZE_VAR),
            400,
        )


# --------------------------------------------------------------------------
# endpoint urls
# --------------------------------------------------------------------------


def dataset_endpoint(ident: str) -> str:
    """The endpoint a caller should follow for a dataset.

    With REQUIRE_TLS on, callers are handed an absolute https URL on the host
    they asked for, so a plain-http hop cannot be inherited from the request.
    """
    path = "/datasets/%s" % ident
    if CONFIG.require_tls:
        return "https://%s%s" % (request.host, path)
    return path


# --------------------------------------------------------------------------
# url / charset validation
# --------------------------------------------------------------------------


def validate_source(source: str) -> str:
    if source is None:
        raise DataGateError("missing required query parameter: source", 400)
    source = source.strip()
    if not source:
        raise DataGateError("missing required query parameter: source", 400)
    try:
        parsed = urlparse(source)
    except ValueError:
        raise DataGateError("invalid url: %s" % source, 400)
    if parsed.scheme.lower() not in ("http", "https"):
        raise DataGateError(
            "invalid url: only http and https urls are supported", 400
        )
    if not parsed.netloc or not parsed.hostname:
        raise DataGateError("invalid url: missing host", 400)
    if any(ch.isspace() for ch in source):
        raise DataGateError("invalid url: whitespace is not allowed", 400)
    return source


def validate_charset(charset):
    """Return a normalised codec name, or None when no charset was supplied."""
    if charset is None:
        return None
    charset = charset.strip()
    if not charset:
        return None
    try:
        info = codecs.lookup(charset)
    except (LookupError, TypeError, ValueError):
        raise DataGateError("unsupported or malformed charset: %s" % charset, 400)
    return info.name


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------


def fetch(source: str) -> bytes:
    try:
        response = requests.get(
            source,
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
            stream=True,
        )
    except requests.RequestException as exc:
        raise DataGateError("source unreachable: %s" % exc, 404)
    try:
        if response.status_code >= 400:
            raise DataGateError(
                "remote http error: %d for %s" % (response.status_code, source), 404
            )
        chunks = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                # stop as soon as the configured maximum is passed rather than
                # buffering a source that is already known to be rejected
                enforce_source_size(total)
                if total > MAX_DOWNLOAD_BYTES:
                    raise DataGateError("source is too large to process", 400)
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise DataGateError("source unreachable: %s" % exc, 404)
        return b"".join(chunks)
    finally:
        response.close()


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------

_BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]


def decode_with_charset(data: bytes, charset: str) -> str:
    try:
        return data.decode(charset)
    except (UnicodeDecodeError, LookupError, ValueError) as exc:
        raise DataGateError(
            "unsupported or malformed charset: cannot decode content as %s (%s)"
            % (charset, exc),
            400,
        )


def detect_and_decode(data: bytes) -> str:
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                break
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            encoding = best.encoding
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                return str(best)
    except Exception:
        pass
    for encoding in ("cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# csv parsing
# --------------------------------------------------------------------------


def _looks_non_tabular(text: str, raw: bytes) -> None:
    stripped = text.strip().lstrip("﻿").strip()
    if not stripped:
        raise DataGateError("non-tabular content: source is empty", 400)
    if "\x00" in text:
        raise DataGateError("non-tabular content: source is binary", 400)
    if stripped[0] == "<":
        raise DataGateError(
            "non-tabular content: source looks like markup, not tabular data", 400
        )
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
        except ValueError:
            pass
        else:
            raise DataGateError(
                "non-tabular content: source looks like json, not tabular data", 400
            )
    if raw[:4] in (b"%PDF", b"PK\x03\x04") or raw[:2] == b"\x1f\x8b":
        raise DataGateError("non-tabular content: source is binary", 400)


def _parse_rows(text: str, delimiter: str):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = []
    try:
        for row in reader:
            if not row or all(cell.strip() == "" for cell in row):
                continue
            rows.append(row)
    except csv.Error as exc:
        raise DataGateError("non-tabular content: %s" % exc, 400)
    return rows


MIN_CONSISTENCY = 0.5


def _score(rows) -> tuple:
    """Higher is better: (has_columns, consistency, column_count).

    ``consistency`` is the share of rows whose field count matches the header;
    a real delimiter splits every row the same way, a coincidental one does not.
    """
    if len(rows) < 2:
        return (0, 0.0, 0)
    header_len = len(rows[0])
    if header_len < 2:
        return (0, 0.0, header_len)
    matching = sum(1 for row in rows if len(row) == header_len)
    consistency = matching / len(rows)
    return (1, round(consistency, 6), header_len)


def sniff_and_parse(text: str, raw: bytes):
    """Return (columns, rows) parsed with the inferred delimiter."""
    _looks_non_tabular(text, raw)

    text = text.lstrip("﻿")

    best = None
    best_key = None
    for index, delimiter in enumerate(CANDIDATE_DELIMITERS):
        try:
            rows = _parse_rows(text, delimiter)
        except DataGateError:
            continue
        score = _score(rows)
        # prefer earlier delimiters on ties (deterministic)
        key = (score[0], score[1], score[2], -index)
        if best_key is None or key > best_key:
            best_key = key
            best = rows

    if best is None or best_key is None or best_key[0] == 0 or best_key[1] < MIN_CONSISTENCY:
        # No delimiter produced a consistent multi-column table.
        try:
            lines = _parse_rows(text, ",")
        except DataGateError:
            lines = []
        if len(lines) < 2:
            raise DataGateError(
                "non-tabular content: a valid file requires at least one header row "
                "and one data row",
                400,
            )
        raise DataGateError(
            "non-tabular content: could not infer a delimiter (',', ';' or tab) "
            "producing a consistent table",
            400,
        )

    rows = best

    header = [cell.strip().lstrip("﻿") for cell in rows[0]]
    width = len(header)
    data_rows = []
    for row in rows[1:]:
        if len(row) < width:
            row = list(row) + [""] * (width - len(row))
        elif len(row) > width:
            row = list(row[:width])
        data_rows.append([convert_value(cell) for cell in row])

    if not data_rows:
        raise DataGateError(
            "non-tabular content: a valid file requires at least one header row "
            "and one data row",
            400,
        )
    return header, data_rows


# --------------------------------------------------------------------------
# type inference
# --------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")
_DEC_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)$")
_SCI_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?$")


def convert_value(value: str):
    """Deterministically convert a raw CSV cell to a JSON-friendly value."""
    if value is None:
        return ""
    text = value.strip()
    if not text:
        return ""
    # time-like values (08:30, 9:15, 12:00, 12:00:30) stay text
    if ":" in text or _TIME_RE.match(text):
        return text
    if _INT_RE.match(text):
        try:
            return int(text)
        except ValueError:
            return text
    if _DEC_RE.match(text) or _SCI_RE.match(text):
        try:
            number = float(text)
        except ValueError:
            return text
        if math.isfinite(number):
            return number
        return text
    return text


# --------------------------------------------------------------------------
# multi-format ingestion (csv / xls / xlsx)
# --------------------------------------------------------------------------


def _zip_looks_like_xlsx(raw: bytes) -> bool:
    """True when the zip container holds an OOXML spreadsheet part."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    return any(name.startswith("xl/") for name in names)


def detect_format(raw: bytes) -> str:
    """Return ``"csv"``, ``"xls"``, ``"xlsx"`` or ``"unknown"`` for the bytes.

    The container is decided by content, not by the file name: an ``.xls`` that
    is really a CSV still parses, and a CSV named ``.txt`` still parses.
    """
    if raw.startswith(OLE2_SIGNATURE) or raw.startswith(BIFF_SIGNATURES):
        return "xls"
    if raw.startswith(ZIP_SIGNATURES):
        return "xlsx" if _zip_looks_like_xlsx(raw) else "unknown"
    return "csv"


def sheet_value(value):
    """Map a spreadsheet cell onto the same value model CSV cells use."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        # whole numbers are stored as floats by both readers; a CSV "30" yields
        # the int 30, so spreadsheets have to agree.
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        return value
    if isinstance(value, datetime.datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.time):
        if (value.second, value.microsecond) == (0, 0):
            return value.strftime("%H:%M")
        return value.strftime("%H:%M:%S")
    if isinstance(value, datetime.timedelta):
        return str(value)
    return convert_value(str(value))


def header_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lstrip("\ufeff")


def table_from_grid(grid):
    """Turn a rectangular-ish sheet grid into ``(columns, rows)``.

    Trailing all-empty columns and fully empty rows are dropped first: they are
    formatting artefacts, not data. What is left must still be a header row plus
    at least one data row.
    """
    normalised = [[sheet_value(cell) for cell in row] for row in grid]

    width = 0
    for row in normalised:
        for index, cell in enumerate(row):
            if cell != "":
                width = max(width, index + 1)

    kept = [row for row in normalised if any(cell != "" for cell in row)]
    if width == 0 or len(kept) < 2:
        raise DataGateError(
            "non-tabular content: a valid file requires at least one header row "
            "and one data row",
            400,
        )

    header = [header_text(cell) for cell in kept[0][:width]]
    if len(header) < width:
        header += [""] * (width - len(header))

    rows = []
    for row in kept[1:]:
        row = list(row[:width])
        if len(row) < width:
            row += [""] * (width - len(row))
        rows.append(row)
    return header, rows


def parse_xlsx(raw: bytes):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DataGateError("xlsx support is unavailable: %s" % exc, 400)

    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except DataGateError:
        raise
    except Exception as exc:
        raise DataGateError("unsupported format: cannot read xlsx (%s)" % exc, 400)

    try:
        sheets = workbook.worksheets
        if not sheets:
            raise DataGateError("non-tabular content: workbook has no worksheets", 400)
        # only the first worksheet is ingested
        grid = [list(row) for row in sheets[0].iter_rows(values_only=True)]
    except DataGateError:
        raise
    except Exception as exc:
        raise DataGateError("unsupported format: cannot read xlsx (%s)" % exc, 400)
    finally:
        try:
            workbook.close()
        except Exception:  # pragma: no cover - close is best effort
            pass

    return table_from_grid(grid)


def parse_xls(raw: bytes):
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DataGateError("xls support is unavailable: %s" % exc, 400)

    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as exc:
        raise DataGateError("unsupported format: cannot read xls (%s)" % exc, 400)

    try:
        if book.nsheets < 1:
            raise DataGateError("non-tabular content: workbook has no worksheets", 400)
        sheet = book.sheet_by_index(0)  # only the first worksheet is ingested
        grid = []
        for index in range(sheet.nrows):
            grid.append(
                [
                    _xls_cell(cell, book.datemode)
                    for cell in sheet.row(index)
                ]
            )
    except DataGateError:
        raise
    except Exception as exc:
        raise DataGateError("unsupported format: cannot read xls (%s)" % exc, 400)
    finally:
        try:
            book.release_resources()
        except Exception:  # pragma: no cover - close is best effort
            pass

    return table_from_grid(grid)


def _xls_cell(cell, datemode):
    import xlrd

    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            if cell.value < 1:
                # a time of day carries no date component in a BIFF serial
                _, _, _, hour, minute, second = xlrd.xldate_as_tuple(
                    cell.value, datemode
                )
                return datetime.time(hour, minute, second)
            return xlrd.xldate.xldate_as_datetime(cell.value, datemode)
        except Exception:
            return cell.value
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    return cell.value


def ingest_detailed(raw: bytes, charset=None):
    """Parse bytes into ``(columns, rows, kind)``.

    ``kind`` is the container the bytes turned out to hold ("csv", "xls" or
    "xlsx"); enrichment reports it and nothing else needs it.

    ``charset`` is only meaningful for text CSV sources; a spreadsheet carries
    its own encoding inside the container and ignores it.
    """
    kind = detect_format(raw)
    if kind == "xlsx":
        columns, rows = parse_xlsx(raw)
    elif kind == "xls":
        columns, rows = parse_xls(raw)
    elif kind == "unknown":
        raise DataGateError(
            "unsupported format: expected csv, xls or xlsx content", 400
        )
    else:
        if charset:
            text = decode_with_charset(raw, charset)
        else:
            text = detect_and_decode(raw)
        columns, rows = sniff_and_parse(text, raw)
    return columns, rows, kind


def ingest(raw: bytes, charset=None):
    """Parse uploaded/fetched bytes into ``(columns, rows)``."""
    columns, rows, _kind = ingest_detailed(raw, charset)
    return columns, rows


# --------------------------------------------------------------------------
# optional ingestion enrichment
# --------------------------------------------------------------------------


def wants_enrichment() -> bool:
    """True when the request asked for enrichment.

    Only the exact spelling ``enrich=yes`` turns it on: a missing parameter, a
    bare ``enrich``, another value, a different case and a repeated parameter
    all leave ingestion unenriched rather than being rejected.
    """
    return request.args.getlist(ENRICH_PARAM) == [ENRICH_ENABLED_VALUE]


def is_missing(value) -> bool:
    """A cell counts as missing when it carries no value at all."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def numeric_kind(value):
    """``"integer"``/``"float"`` for a numeric cell, ``None`` for anything else.

    Cells arrive already typed by :func:`convert_value`/:func:`sheet_value`, but
    a dataset reloaded from storage may still hold numbers spelled as text, so
    strings are re-read with the same rules the parser used.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return TYPE_INTEGER
    if isinstance(value, float):
        return TYPE_FLOAT if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            return None
        if _INT_RE.match(text):
            return TYPE_INTEGER
        if _DEC_RE.match(text) or _SCI_RE.match(text):
            return TYPE_FLOAT
    return None


def column_type(values) -> str:
    """Label a column from the values it actually holds.

    Whole numbers make an ``integer`` column and decimals a ``float`` one; a
    column holding both is the wider ``number``. Anything non-numeric -- and a
    column with nothing but missing cells -- is ``text``.
    """
    kinds = set()
    for value in values:
        if is_missing(value):
            continue
        kind = numeric_kind(value)
        if kind is None:
            return TYPE_TEXT
        kinds.add(kind)
    if not kinds:
        return TYPE_TEXT
    if kinds == {TYPE_INTEGER}:
        return TYPE_INTEGER
    if kinds == {TYPE_FLOAT}:
        return TYPE_FLOAT
    return TYPE_NUMBER


def build_column_details(columns, rows) -> dict:
    """Per-column profile, keyed by column name."""
    details = {}
    for index, name in enumerate(columns):
        present = []
        missing = 0
        for row in rows:
            value = row[index] if index < len(row) else ""
            if is_missing(value):
                missing += 1
            else:
                present.append(value)
        # distinctness is judged on the rendered cell, the same text the
        # filters and the CSV export compare against.
        distinct = {cell_text(value) for value in present}
        details[name] = {
            "type": column_type(present),
            "distinct_count": len(distinct),
            "missing_count": missing,
        }
    return details


def build_metadata(kind: str, columns, rows) -> dict:
    """The metadata an enriched ingestion stores alongside the rows.

    A CSV is profiled column by column as well; a workbook only reports the
    dataset-level summary.
    """
    filetype = CSV_FILETYPE if kind == "csv" else EXCEL_FILETYPE
    metadata = {
        "dataset_summary": {
            "filetype": filetype,
            "row_count": len(rows),
            "column_count": len(columns),
        }
    }
    if filetype == CSV_FILETYPE:
        metadata["column_details"] = build_column_details(columns, rows)
    return metadata


def enrich_metadata(kind: str, columns, rows) -> dict:
    """Compute enrichment, turning any failure into a JSON error.

    The caller runs this *before* storing anything, so a failed enrichment
    never replaces a stored dataset with an unenriched one.
    """
    try:
        return build_metadata(kind, columns, rows)
    except DataGateError:
        raise
    except Exception as exc:
        raise DataGateError("enrichment failed: %s" % exc, 500)


# --------------------------------------------------------------------------
# dataset identity / storage
# --------------------------------------------------------------------------


def dataset_id(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def content_id(raw: bytes) -> str:
    """Identity for uploads: the same bytes always land on the same dataset."""
    return hashlib.sha256(raw).hexdigest()[:16]


def dataset_path(ident: str) -> str:
    return os.path.join(CONFIG.storage_dir, "%s.json" % ident)


def valid_dataset_id(ident) -> bool:
    """Only ids that name one file inside the storage directory are looked up."""
    return bool(ident) and bool(DATASET_ID_RE.match(ident))


def persist_dataset(ident: str, record: dict) -> None:
    """Write a dataset out so it survives a restart on the same STORAGE_DIR.

    The write goes through a temporary file and a rename, so a reader never sees
    a half-written dataset and a replaced dataset is swapped in whole.
    """
    final = dataset_path(ident)
    temporary = "%s.%d.tmp" % (final, os.getpid())
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.replace(temporary, final)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DataGateError(
            "cannot persist dataset to %s: %s" % (CONFIG.storage_dir, exc), 500
        )


def read_persisted(ident: str):
    """Load a dataset written by an earlier run, or ``None`` when there is none."""
    try:
        with open(dataset_path(ident), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    columns, rows = record.get("columns"), record.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    stored = {
        "source": record.get("source", ""),
        "columns": list(columns),
        "rows": [list(row) for row in rows],
        "enriched": False,
    }
    # enrichment is part of the stored dataset, so it survives a restart; a
    # record without a usable summary is simply an unenriched one.
    summary = record.get("dataset_summary")
    if record.get("enriched") and isinstance(summary, dict):
        stored["enriched"] = True
        stored["dataset_summary"] = dict(summary)
        details = record.get("column_details")
        if isinstance(details, dict):
            stored["column_details"] = dict(details)
    return stored


def store_dataset(ident: str, source: str, columns, rows, metadata=None) -> None:
    """Store a dataset, with its enrichment metadata when it was enriched.

    Whatever this ingestion produced replaces the stored dataset whole, so the
    stored enrichment state is always the one this ingestion computed.
    """
    record = {
        "source": source,
        "columns": columns,
        "rows": rows,
        "enriched": metadata is not None,
    }
    if metadata:
        record.update(metadata)
    with _LOCK:
        _DATASETS[ident] = record
    persist_dataset(ident, record)


def load_dataset(ident: str) -> dict:
    with _LOCK:
        stored = _DATASETS.get(ident)
    if stored is None and valid_dataset_id(ident):
        stored = read_persisted(ident)
        if stored is not None:
            with _LOCK:
                stored = _DATASETS.setdefault(ident, stored)
    if stored is None:
        raise DataGateError("unknown dataset: %s" % ident, 404)
    return stored


def dataset_is_enriched(ident: str) -> bool:
    """True when the stored dataset already carries enrichment metadata."""
    with _LOCK:
        stored = _DATASETS.get(ident)
    if stored is None:
        if not valid_dataset_id(ident):
            return False
        stored = read_persisted(ident)
    return bool(stored is not None and stored.get("enriched"))


def dataset_exists(ident: str) -> bool:
    with _LOCK:
        if ident in _DATASETS:
            return True
    return valid_dataset_id(ident) and os.path.exists(dataset_path(ident))


# --------------------------------------------------------------------------
# the /convert cache
# --------------------------------------------------------------------------


def cache_key(source: str, charset) -> tuple:
    """Two requests share a cached result only when they parse identically.

    ``charset`` decides how the same bytes are decoded, so it is part of the
    identity of the result even though the dataset id is derived from the url.
    """
    return (source, charset or "")


def cache_lookup(source: str, charset):
    """Return the cached dataset id for a source, or ``None`` for a miss.

    A cached id whose dataset is gone is a miss: the answer has to stay
    indistinguishable from a fresh parse.
    """
    if not CONFIG.cache_enabled:
        return None
    key = cache_key(source, charset)
    with _LOCK:
        ident = _CACHE.get(key)
    if ident is None or not dataset_exists(ident):
        return None
    return ident


def cache_remember(source: str, charset, ident: str) -> None:
    with _LOCK:
        _CACHE[cache_key(source, charset)] = ident


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


def wants_reingest() -> bool:
    """``force`` is a presence flag: given once it bypasses the cache.

    Its value carries no meaning, but repeating it is ambiguous and rejected.
    """
    values = request.args.getlist(FORCE_PARAM)
    if len(values) > 1:
        raise DataGateError(
            "invalid %s: repeated query parameter, %s may only be given once"
            % (FORCE_PARAM, FORCE_PARAM),
            400,
        )
    return bool(values)


@app.route("/convert", methods=["GET", "OPTIONS"])
def convert():
    if request.method == "OPTIONS":
        return ("", 204)

    if "source" not in request.args:
        raise DataGateError("missing required query parameter: source", 400)
    source = validate_source(request.args.get("source"))
    charset = validate_charset(request.args.get("charset"))
    forced = wants_reingest()
    enrich = wants_enrichment()

    if not forced:
        cached = cache_lookup(source, charset)
        # asking for enrichment on a dataset that was stored without it is a
        # cache miss: the request has to re-ingest to upgrade what is stored.
        if cached is not None and (not enrich or dataset_is_enriched(cached)):
            # a cache hit answers exactly like a fresh parse, minus the download
            return ok({"endpoint": dataset_endpoint(cached)})

    # a failed ingestion -- enrichment included -- raises before anything is
    # stored, so the previously ingested dataset stays queryable under its id
    # with the enrichment state it already had.
    raw = fetch(source)
    enforce_source_size(len(raw))
    columns, rows, kind = ingest_detailed(raw, charset)
    # metadata always describes the bytes this ingestion just parsed
    metadata = enrich_metadata(kind, columns, rows) if enrich else None

    ident = dataset_id(source)
    store_dataset(ident, source, columns, rows, metadata)
    cache_remember(source, charset, ident)

    return ok({"endpoint": dataset_endpoint(ident)})


# --------------------------------------------------------------------------
# file upload
# --------------------------------------------------------------------------


def read_upload():
    """Return ``(bytes, filename)`` for the uploaded part.

    A request that is not a multipart form cannot carry a file part at all, so
    it is rejected as an unsupported media type; a multipart body that does not
    parse, or that carries neither ``file`` nor ``attachment``, is a bad request.
    """
    if request.mimetype != MULTIPART_MIMETYPE:
        raise DataGateError(
            "unsupported media type: expected a %s upload with a 'file' or "
            "'attachment' part" % MULTIPART_MIMETYPE,
            415,
        )

    parser = FormDataParser(
        silent=False,
        max_form_memory_size=None,
        max_content_length=MAX_DOWNLOAD_BYTES,
        max_form_parts=None,
    )
    try:
        _, form, files = parser.parse_from_environ(request.environ)
    except HTTPException:
        raise
    except ValueError as exc:
        raise DataGateError("malformed multipart upload: %s" % exc, 400)

    for field in UPLOAD_FIELDS:
        storage = files.get(field)
        if storage is not None:
            return storage.read(), (storage.filename or "")
    for field in UPLOAD_FIELDS:
        if field in form:
            return form[field].encode("utf-8"), ""

    raise DataGateError(
        "missing file field: the upload must contain a '%s' or '%s' part"
        % UPLOAD_FIELDS,
        400,
    )


@app.route("/upload", methods=["POST", "OPTIONS"])
def upload():
    if request.method == "OPTIONS":
        return ("", 204)

    charset = validate_charset(request.args.get("charset"))
    raw, filename = read_upload()
    enforce_source_size(len(raw))
    columns, rows = ingest(raw, charset)

    ident = content_id(raw)
    store_dataset(ident, "upload:%s" % (filename or "file"), columns, rows)

    return ok({"endpoint": dataset_endpoint(ident)})


# --------------------------------------------------------------------------
# control parameters (pagination, sorting, response shape)
# --------------------------------------------------------------------------

_SIGNED_INT_RE = re.compile(r"^[+-]?\d+$")


def single_param(name: str):
    """Return the sole value given for a control parameter, else ``None``.

    Supplying a control parameter more than once is ambiguous, so it is an
    error rather than a silent "last one wins".
    """
    values = request.args.getlist(name)
    if len(values) > 1:
        raise DataGateError(
            "invalid %s: repeated query parameter, %s may only be given once"
            % (name, name),
            400,
        )
    return values[0] if values else None


def parse_bounded_int(raw: str, name: str, minimum: int, described: str) -> int:
    text = raw.strip()
    if not _SIGNED_INT_RE.match(text):
        raise DataGateError("invalid %s: %s must be %s" % (name, name, described), 400)
    value = int(text)
    if value < minimum:
        raise DataGateError("invalid %s: %s must be %s" % (name, name, described), 400)
    return value


def parse_hide_toggle(raw, name: str) -> bool:
    """``_rowid``/``_total`` accept only the literal value ``hide``."""
    if raw is None:
        return False
    if raw != "hide":
        raise DataGateError(
            "invalid %s: the only supported value is 'hide'" % name, 400
        )
    return True


def parse_shape(raw) -> str:
    if raw is None:
        return "lists"
    if raw not in SHAPES:
        raise DataGateError(
            "invalid _shape: expected one of %s" % ", ".join(SHAPES), 400
        )
    return raw


def resolve_sort(columns):
    """Return ``(column_index, descending)`` or ``None`` when unsorted.

    ``_sort_desc`` wins when both are supplied, but both are still validated:
    naming a column that does not exist is an error either way.
    """
    ascending = single_param("_sort")
    descending = single_param("_sort_desc")

    chosen = None
    for raw, name, reverse in ((ascending, "_sort", False), (descending, "_sort_desc", True)):
        if raw is None:
            continue
        if not raw:
            raise DataGateError("invalid %s: column name must not be empty" % name, 400)
        if raw not in columns:
            raise DataGateError("invalid %s: unknown column: %s" % (name, raw), 400)
        chosen = (columns.index(raw), reverse)
    return chosen


def sort_key(value):
    """Order mixed CSV cell types deterministically: blanks, numbers, text.

    A column can hold both numbers and text, which Python refuses to compare,
    so every cell is mapped onto a uniform ``(rank, number, text)`` tuple.
    """
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, (int, float)):
        return (1, float(value), "")
    text = str(value)
    if not text:
        return (0, 0.0, "")
    return (2, 0.0, text)


def legacy_int_param(name: str, default: int) -> int:
    """Support the pre-existing ``limit``/``offset`` spelling."""
    raw = request.args.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise DataGateError("invalid %s: %s" % (name, raw), 400)
    if value < 0:
        raise DataGateError("invalid %s: %s" % (name, raw), 400)
    return value


# --------------------------------------------------------------------------
# column-level filtering
# --------------------------------------------------------------------------


def cell_text(value) -> str:
    """The string form a cell is compared against by ``exact``/``contains``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def cell_number(value):
    """Return ``value`` as a float, or ``None`` when it does not parse as one.

    Stored cells arrive already typed by :func:`convert_value`, but a column may
    still mix numbers with text; a cell that is not numeric simply never matches
    a numeric comparator.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class QueryBudget:
    """Wall-clock ceiling on a single ``/datasets`` query."""

    def __init__(self, started: float, limit_ms):
        self.started = started
        self.limit_ms = limit_ms

    def elapsed_ms(self) -> float:
        return max(0.0, (time.perf_counter() - self.started) * 1000.0)

    def check(self) -> None:
        if self.limit_ms is None:
            return
        elapsed = self.elapsed_ms()
        if elapsed > self.limit_ms:
            raise DataGateError(
                "query timeout: the query exceeded its %s ms time limit "
                "(%.1f ms elapsed)" % (self.limit_ms, elapsed),
                400,
            )


def resolve_timeout_ms():
    raw = single_param("_timeout_ms")
    if raw is None:
        return DEFAULT_QUERY_TIMEOUT_MS
    return parse_bounded_int(
        raw, "_timeout_ms", 0, "a non-negative integer number of milliseconds"
    )


def parse_filters(columns):
    """Turn ``<column>__<comparator>=<value>`` query params into filter specs.

    Returns a list of ``(column_index, comparator, value, number)`` tuples;
    ``number`` is the pre-parsed float for the numeric comparators and ``None``
    otherwise. Anything that is not filter-shaped is ignored rather than
    rejected, so control parameters and stray extras still pass through.
    """
    filters = []
    seen = set()
    for key in request.args.keys():
        if key in seen:
            continue
        seen.add(key)
        if key.startswith("_"):
            # a control parameter, never a filter
            continue
        if FILTER_SEPARATOR not in key:
            # not filter-shaped, ignored
            continue

        values = request.args.getlist(key)
        if len(values) > 1:
            raise DataGateError(
                "invalid filter %s: repeated filter parameter, %s may only be "
                "given once" % (key, key),
                400,
            )

        column, _, comparator = key.rpartition(FILTER_SEPARATOR)
        if comparator not in COMPARATORS:
            raise DataGateError(
                "invalid filter %s: unknown comparator: %s (expected one of %s)"
                % (key, comparator, ", ".join(COMPARATORS)),
                400,
            )
        if column not in columns:
            raise DataGateError(
                "invalid filter %s: unknown column: %s" % (key, column), 400
            )

        value = values[0]
        number = None
        if comparator in NUMERIC_COMPARATORS:
            number = cell_number(value)
            if number is None:
                raise DataGateError(
                    "invalid filter %s: __%s requires a numeric value, got: %s"
                    % (key, comparator, value),
                    400,
                )
        filters.append((columns.index(column), comparator, value, number))
    return filters


def row_matches(row, filters) -> bool:
    """Every filter must hold: multiple filters are ANDed."""
    for index, comparator, value, number in filters:
        cell = row[index]
        if comparator == "exact":
            if cell_text(cell) != value:
                return False
        elif comparator == "contains":
            if value not in cell_text(cell):
                return False
        else:
            stored = cell_number(cell)
            if stored is None:
                return False
            if comparator == "less":
                if not stored < number:
                    return False
            elif not stored > number:
                return False
    return True


FILTER_BUDGET_STRIDE = 512


def apply_filters(numbered, filters, budget: QueryBudget):
    budget.check()
    if not filters:
        return numbered
    kept = []
    for position, pair in enumerate(numbered):
        if position % FILTER_BUDGET_STRIDE == 0:
            budget.check()
        if row_matches(pair[1], filters):
            kept.append(pair)
    budget.check()
    return kept


class QuerySpec:
    """The parsed control/filter parameters of one dataset query."""

    def __init__(self, columns, budget):
        self.budget = budget
        self.shape = parse_shape(single_param("_shape"))
        self.hide_rowid = parse_hide_toggle(single_param("_rowid"), "_rowid")
        self.hide_total = parse_hide_toggle(single_param("_total"), "_total")
        self.sort = resolve_sort(columns)
        self.filters = parse_filters(columns)

        raw_size = single_param("_size")
        if raw_size is None:
            self.size = legacy_int_param("limit", DEFAULT_ROW_LIMIT)
        else:
            self.size = parse_bounded_int(raw_size, "_size", 1, "a positive integer")

        raw_offset = single_param("_offset")
        if raw_offset is None:
            self.offset = legacy_int_param("offset", 0)
        else:
            self.offset = parse_bounded_int(
                raw_offset, "_offset", 0, "a non-negative integer"
            )


def build_query(columns, started: float) -> QuerySpec:
    return QuerySpec(columns, QueryBudget(started, resolve_timeout_ms()))


def select_rows(stored, spec: QuerySpec):
    """Apply filter -> sort -> paginate; returns ``(window, total)``.

    ``window`` holds ``(rowid, row)`` pairs and ``total`` counts the filtered
    rows before the pagination window is taken.
    """
    # rowid is the 1-based position in the source file, so it is attached before
    # filtering and sorting and survives both.
    numbered = list(enumerate(stored["rows"], start=1))

    numbered = apply_filters(numbered, spec.filters, spec.budget)
    total = len(numbered)

    if spec.sort is not None:
        index, reverse = spec.sort
        # list.sort is stable, and stays stable under reverse=True: equal keys
        # keep their source-file order rather than being flipped.
        numbered.sort(key=lambda pair: sort_key(pair[1][index]), reverse=reverse)
        spec.budget.check()

    return numbered[spec.offset : spec.offset + spec.size], total


@app.route("/datasets/<dataset>", methods=["GET", "OPTIONS"])
def get_dataset(dataset: str):
    if request.method == "OPTIONS":
        return ("", 204)

    started = time.perf_counter()
    stored = load_dataset(dataset)
    columns = list(stored["columns"])

    spec = build_query(columns, started)
    shape, hide_rowid, hide_total = spec.shape, spec.hide_rowid, spec.hide_total
    window, total = select_rows(stored, spec)

    if shape == "objects":
        rows = []
        for rowid, row in window:
            record = {"rowid": rowid} if not hide_rowid else {}
            record.update(zip(columns, row))
            rows.append(record)
    else:
        rows = [list(row) for _, row in window]

    query_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    payload = {"columns": columns, "rows": rows}
    if not hide_total:
        payload["total"] = total
    payload["query_ms"] = round(query_ms, 4)
    # an unenriched dataset carries no metadata fields at all, rather than
    # empty ones; enrichment describes the dataset, not this query's window.
    if stored.get("enriched"):
        summary = stored.get("dataset_summary")
        if isinstance(summary, dict):
            payload["dataset_summary"] = dict(summary)
        details = stored.get("column_details")
        if isinstance(details, dict):
            payload["column_details"] = {
                name: dict(entry) if isinstance(entry, dict) else entry
                for name, entry in details.items()
            }
    return ok(payload)


@app.route("/datasets/<dataset>/export", methods=["GET", "OPTIONS"])
def export_dataset(dataset: str):
    """The same rows as ``/datasets/<id>``, serialised back to CSV.

    Response shape parameters (``_shape``, ``_rowid``, ``_total``) are still
    validated but cannot change a CSV body: it is always the source columns in
    source order followed by the filtered, sorted, paginated rows.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    started = time.perf_counter()
    stored = load_dataset(dataset)
    columns = list(stored["columns"])

    spec = build_query(columns, started)
    window, _total = select_rows(stored, spec)

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for _rowid, row in window:
        writer.writerow([cell_text(cell) for cell in row])

    response = app.response_class(buffer.getvalue().encode("utf-8"), status=200)
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = (
        'attachment; filename="%s.csv"' % dataset
    )
    return response


@app.route("/", methods=["GET", "OPTIONS"])
def index():
    if request.method == "OPTIONS":
        return ("", 204)
    return ok(
        {
            "service": "datagate",
            "endpoints": [
                "/convert?source=<url>[&charset=<charset>]",
                "/upload",
                "/datasets/<id>",
                "/datasets/<id>/export",
            ],
        }
    )


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagate", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="start the datagate http server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in (None, "start"):
        parser.error("unknown command: %s" % args.command)
    if _CONFIG_ERROR is not None:
        print("configuration error: %s" % _CONFIG_ERROR, file=sys.stderr)
        return 2
    app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

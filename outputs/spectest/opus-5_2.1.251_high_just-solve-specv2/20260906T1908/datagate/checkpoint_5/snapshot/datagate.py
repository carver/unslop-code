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

# `/convert` caches by default; `CACHE_ENABLED` in the environment turns that
# off. The accepted spellings are exhaustive and matched case-insensitively --
# anything else is a configuration mistake and stops the server from starting.
CACHE_ENV_VAR = "CACHE_ENABLED"
CACHE_TRUE_VALUES = ("1", "true", "yes", "on")
CACHE_FALSE_VALUES = ("0", "false", "no", "off")
DEFAULT_CACHE_ENABLED = True

# `force` is a presence flag on /convert: `?force` re-ingests, `?force=1` is a
# mistake worth reporting rather than guessing at.
FORCE_PARAM = "force"

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class DatasetStore:
    """Thread-safe in-memory dataset store keyed by a deterministic id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._ingest_locks: Dict[str, threading.Lock] = {}

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
# Environment configuration
# --------------------------------------------------------------------------


def parse_cache_enabled(raw: Optional[str]) -> bool:
    """Read one `CACHE_ENABLED` spelling, defaulting to caching enabled.

    Only the documented words are accepted, in any case combination. A value
    that merely looks boolean (`"maybe"`, `"2"`, `"true "`, `""`) is rejected
    rather than guessed at, because silently caching when the operator asked
    for no caching is the kind of mistake that surfaces much later.
    """
    if raw is None:
        return DEFAULT_CACHE_ENABLED
    token = raw.lower()
    if token in CACHE_TRUE_VALUES:
        return True
    if token in CACHE_FALSE_VALUES:
        return False
    raise ConfigError(
        "Invalid %s value %r: expected one of %s."
        % (
            CACHE_ENV_VAR,
            raw,
            ", ".join(repr(v) for v in CACHE_TRUE_VALUES + CACHE_FALSE_VALUES),
        )
    )


def load_cache_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """Resolve `CACHE_ENABLED` from the environment."""
    source = os.environ if env is None else env
    return parse_cache_enabled(source.get(CACHE_ENV_VAR))


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


def fetch_source(url: str) -> bytes:
    """Download the source URL, mapping every transport failure onto 404."""
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
        chunks: List[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    break
        except requests.exceptions.RequestException as exc:
            raise NotFound("Source unreachable: %s" % _brief(exc)) from None
        return b"".join(chunks)[:MAX_DOWNLOAD_BYTES]
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


def ingest(raw: bytes, charset_param: Optional[str]) -> Tuple[List[str], List[List[Any]]]:
    """Turn raw source bytes into a header plus typed data rows.

    `charset` only ever applies to text CSV sources; a workbook carries its
    own encoding, so the parameter is neither used nor validated for one.
    """
    kind = detect_format(raw)
    if kind == FORMAT_XLSX:
        return read_xlsx(raw)
    if kind == FORMAT_XLS:
        return read_xls(raw)

    charset = validate_charset(charset_param)
    text = decode_bytes(raw, charset)
    columns, rows = parse_tabular(raw, text)
    return columns, [[coerce(cell) for cell in row] for row in rows]


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


def create_app(cache_enabled: Optional[bool] = None) -> Flask:
    if cache_enabled is None:
        cache_enabled = load_cache_enabled()

    app = Flask(__name__)
    app.config["CACHE_ENABLED"] = cache_enabled
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

    def _apply_cors(response) -> None:
        headers = response.headers
        headers.setdefault("Access-Control-Allow-Origin", "*")
        headers.setdefault(
            "Access-Control-Allow-Methods", "GET, HEAD, OPTIONS, POST"
        )
        headers.setdefault("Access-Control-Allow-Headers", "*")
        headers.setdefault("Access-Control-Expose-Headers", "*")
        headers.setdefault("Access-Control-Max-Age", "86400")

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

        charset_param = request.args.get("charset")
        dataset_id = STORE.make_id(source)
        key = cache_key(source, charset_param)
        # `force` and a disabled cache both mean "ingest now"; neither drops
        # the stored dataset up front, so a failure below changes nothing.
        use_cache = cache_enabled and not forced

        if use_cache and STORE.cached(dataset_id, key):
            return ok({"endpoint": "/datasets/%s" % dataset_id})

        with STORE.ingest_lock(dataset_id):
            # A concurrent request for the same source may have filled the
            # cache while this one waited for the lock.
            if use_cache and STORE.cached(dataset_id, key):
                return ok({"endpoint": "/datasets/%s" % dataset_id})
            try:
                raw = fetch_source(source)
                columns, rows = ingest(raw, charset_param)
            except DataGateError as exc:
                return fail(exc.message, exc.status)
            _store_dataset(dataset_id, source, columns, rows, key)

        return ok({"endpoint": "/datasets/%s" % dataset_id})

    @app.route("/upload", methods=["POST", "OPTIONS"])
    def upload():
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        try:
            raw = read_upload(request)
            columns, rows = ingest(raw, upload_charset(request))
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        dataset_id = STORE.make_content_id(raw)
        _store_dataset(dataset_id, "upload:%s" % dataset_id, columns, rows)
        return ok({"endpoint": "/datasets/%s" % dataset_id})

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
                    "/convert?source=<url>[&charset=<name>][&force]",
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
) -> None:
    """Register one parsed dataset under a deterministic id.

    Storing only ever happens after a successful parse, so a failed (or forced
    and then failed) re-ingestion leaves the previous dataset queryable.
    """
    STORE.put(
        dataset_id,
        {
            "source": source,
            "columns": list(columns),
            "rows": rows,
            "rowids": list(range(FIRST_DATA_ROWID, FIRST_DATA_ROWID + len(rows))),
            "cache_key": key,
        },
    )


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

    # A bad CACHE_ENABLED stops the server before it binds a port, so nobody
    # can talk to a datagate whose caching behaviour is undefined.
    try:
        cache_enabled = load_cache_enabled()
    except ConfigError as exc:
        print("datagate: %s" % exc, file=sys.stderr)
        return 2

    app = create_app(cache_enabled=cache_enabled)
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

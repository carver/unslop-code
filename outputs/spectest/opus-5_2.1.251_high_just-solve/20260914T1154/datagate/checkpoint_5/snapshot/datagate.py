"""datagate -- ingest remote or uploaded CSV/XLS/XLSX files and serve them as datasets."""

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
from collections import Counter
from urllib.parse import urlsplit

import requests
from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"

DEFAULT_ROW_LIMIT = 100
MAX_SAMPLE_LINES = 100
FETCH_TIMEOUT = 30
MAX_BYTES = 64 * 1024 * 1024

# Wall-clock budget for evaluating a single /datasets/<id> query.
QUERY_TIMEOUT_SECONDS = 15.0

# How often the query budget is re-checked while scanning rows.
TIMEOUT_CHECK_INTERVAL = 512

# `,`, `;` and `\t` are the required minimum; the rest are best effort.
DELIMITERS = [",", ";", "\t", "|", ":"]

ALLOWED_SCHEMES = ("http", "https")

# --------------------------------------------------------------------------- #
# Environment configuration
# --------------------------------------------------------------------------- #

# Strict, case-insensitive spellings for boolean environment variables.
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")

CACHE_ENABLED_VAR = "CACHE_ENABLED"


class ConfigError(Exception):
    """An unusable environment value: the server refuses to start."""


def parse_bool_env(name: str, raw, default: bool) -> bool:
    """Read one strict boolean environment value.

    Anything outside the accepted spellings is a configuration error rather
    than a silent fallback to the default.
    """
    if raw is None:
        return default
    value = raw.lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigError(
        f"Invalid {name}: expected one of "
        f"{', '.join(TRUE_VALUES + FALSE_VALUES)} (case-insensitive), "
        f"got {raw!r}."
    )


def cache_enabled_from_env(environ=None) -> bool:
    """Whether /convert may serve a previously ingested source from the store."""
    env = os.environ if environ is None else environ
    return parse_bool_env(CACHE_ENABLED_VAR, env.get(CACHE_ENABLED_VAR), True)


try:
    CACHE_ENABLED = cache_enabled_from_env()
except ConfigError as _config_error:
    print(f"datagate: {_config_error}", file=sys.stderr)
    raise SystemExit(2)

# --------------------------------------------------------------------------- #
# Dataset store
# --------------------------------------------------------------------------- #

_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()


def dataset_id_for(source: str) -> str:
    """Stable id for a source URL string (identical across processes/restarts)."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def dataset_id_for_bytes(data: bytes) -> str:
    """Stable id for uploaded content: identical bytes always map to one id."""
    return hashlib.sha256(b"upload\x00" + data).hexdigest()[:16]


def cache_key_for(source: str, charset: str | None):
    """Identify the ingestion that produced a stored dataset.

    A dataset id only depends on the source URL, but the same URL read with a
    different `charset` is a different parse, so the charset takes part in the
    cache key: only a request asking for the same thing is served from cache.
    """
    return (source, None if charset is None else validate_charset(charset))


def store_dataset(dataset_id: str, payload: dict) -> None:
    with _STORE_LOCK:
        _STORE[dataset_id] = payload


def load_dataset(dataset_id: str):
    with _STORE_LOCK:
        return _STORE.get(dataset_id)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DataGateError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


class BadRequest(DataGateError):
    def __init__(self, message: str):
        super().__init__(message, 400)


class NotFound(DataGateError):
    def __init__(self, message: str):
        super().__init__(message, 404)


class QueryTimeout(BadRequest):
    """Raised when evaluating a request exceeds the query budget."""

    def __init__(self, message: str | None = None):
        super().__init__(message or (
            f"Query timeout: the request exceeded the "
            f"{QUERY_TIMEOUT_SECONDS:g}s query budget."
        ))


# --------------------------------------------------------------------------- #
# URL validation
# --------------------------------------------------------------------------- #


def validate_url(raw: str) -> str:
    candidate = (raw or "").strip()
    if not candidate:
        raise BadRequest("Query parameter 'source' is required.")
    try:
        parts = urlsplit(candidate)
    except ValueError:
        raise BadRequest(f"Invalid URL: {raw!r}")

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BadRequest(
            "Invalid URL: 'source' must be an absolute http:// or https:// URL."
        )
    try:
        hostname = parts.hostname
    except ValueError:
        raise BadRequest(f"Invalid URL: {raw!r}")
    if not hostname:
        raise BadRequest("Invalid URL: missing host in 'source'.")
    if any(ch.isspace() for ch in candidate):
        raise BadRequest("Invalid URL: whitespace is not allowed.")
    try:
        parts.port
    except ValueError:
        raise BadRequest("Invalid URL: invalid port in 'source'.")
    return candidate


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #


def fetch_source(url: str) -> bytes:
    try:
        response = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise NotFound(f"Source unreachable: {exc.__class__.__name__}")
    except Exception as exc:  # pragma: no cover - defensive
        raise NotFound(f"Source unreachable: {exc}")

    try:
        if response.status_code >= 400:
            raise NotFound(
                f"Remote server returned HTTP {response.status_code} for the source URL."
            )
        try:
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    break
            return b"".join(chunks)[:MAX_BYTES]
        except requests.exceptions.RequestException as exc:
            raise NotFound(f"Source unreachable: {exc.__class__.__name__}")
    finally:
        response.close()


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #

BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def validate_charset(charset: str) -> str:
    name = (charset or "").strip()
    if not name:
        raise BadRequest("Unsupported charset: charset must be a non-empty name.")
    try:
        return codecs.lookup(name).name
    except (LookupError, TypeError, ValueError):
        raise BadRequest(f"Unsupported charset: {charset!r}")


def decode_with_charset(data: bytes, charset: str) -> str:
    codec = validate_charset(charset)
    try:
        text = data.decode(codec, errors="strict")
    except (UnicodeDecodeError, LookupError, ValueError) as exc:
        raise BadRequest(f"Malformed charset: cannot decode content as {charset!r} ({exc}).")
    return strip_bom(text)


def strip_bom(text: str) -> str:
    return text[1:] if text.startswith("﻿") else text


def detect_decode(data: bytes) -> str:
    """Best-effort encoding detection for the raw CSV bytes."""
    for bom, codec in BOMS:
        if data.startswith(bom):
            try:
                return strip_bom(data.decode(codec))
            except UnicodeDecodeError:
                break

    try:
        return strip_bom(data.decode("utf-8"))
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            encoding = best.encoding
            try:
                return strip_bom(data.decode(encoding, errors="strict"))
            except (UnicodeDecodeError, LookupError):
                return strip_bom(str(best))
    except Exception:
        pass

    for codec in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return strip_bom(data.decode(codec, errors="strict"))
        except (UnicodeDecodeError, LookupError, ValueError):
            continue
    return strip_bom(data.decode("latin-1", errors="replace"))


# --------------------------------------------------------------------------- #
# CSV parsing
# --------------------------------------------------------------------------- #


def looks_binary(data: bytes) -> bool:
    head = data[:8192]
    if not head:
        return False
    for bom, _ in BOMS:
        if data.startswith(bom):
            return False
    if b"\x00" in head:
        return True
    control = sum(1 for b in head if b < 9 or (13 < b < 32))
    return control / len(head) > 0.05


def looks_markup_or_json(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return True
    if stripped[0] == "<":
        return True
    if stripped[:1] in ("{", "["):
        try:
            json.loads(text)
            return True
        except (ValueError, RecursionError):
            return False
    return False


def parse_rows(text: str, delimiter: str, limit: int | None = None) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter,
                        quotechar='"', skipinitialspace=False)
    rows: list[list[str]] = []
    try:
        for row in reader:
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    except csv.Error:
        pass
    return rows


def is_blank_row(row: list[str]) -> bool:
    return not row or all((cell or "").strip() == "" for cell in row)


def score_delimiter(text: str, delimiter: str):
    """Return (consistency, column_count) for parsing `text` with `delimiter`."""
    rows = [r for r in parse_rows(text, delimiter, limit=MAX_SAMPLE_LINES)
            if not is_blank_row(r)]
    if len(rows) < 2:
        return None
    header_len = len(rows[0])
    if header_len < 2:
        return None
    counts = Counter(len(r) for r in rows)
    matching = counts.get(header_len, 0)
    consistency = matching / len(rows)
    return (consistency, header_len)


def sniff_delimiter(text: str) -> str | None:
    best = None
    best_delim = None
    for delim in DELIMITERS:
        score = score_delimiter(text, delim)
        if score is None:
            continue
        if best is None or score > best:
            best, best_delim = score, delim
    if best is None or best[0] < 0.5:
        return None
    return best_delim


def normalise_columns(header: list[str]) -> list[str]:
    columns: list[str] = []
    for index, raw in enumerate(header):
        name = strip_bom((raw or "").strip())
        if not name:
            name = f"column_{index + 1}"
        columns.append(name)
    return columns


def parse_csv(text: str) -> tuple[list[str], list[list]]:
    if looks_markup_or_json(text):
        raise BadRequest("Non-tabular content: the source does not look like a CSV file.")

    delimiter = sniff_delimiter(text)
    if delimiter is None:
        raise BadRequest(
            "Non-tabular content: unable to infer a delimiter or the file has no "
            "header row and at least one data row."
        )

    rows = [r for r in parse_rows(text, delimiter) if not is_blank_row(r)]
    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: a valid file requires a header row and at least "
            "one data row."
        )

    columns = normalise_columns(rows[0])
    width = len(columns)
    if width < 2:
        raise BadRequest("Non-tabular content: no tabular structure detected.")

    data_rows: list[list] = []
    for raw_row in rows[1:]:
        cells = list(raw_row[:width])
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        data_rows.append([coerce_value(cell) for cell in cells])

    if not data_rows:
        raise BadRequest(
            "Non-tabular content: a valid file requires a header row and at least "
            "one data row."
        )
    return columns, data_rows


# --------------------------------------------------------------------------- #
# Type inference (deterministic, locale independent)
# --------------------------------------------------------------------------- #

INT_RE = re.compile(r"^[+-]?\d+$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*(?:[AaPp]\.?[Mm]\.?)?$")


def coerce_value(raw):
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return value

    # Time-like values stay text (08:30, 9:15, 12:00, 08:30:05, 8:30 PM).
    if TIME_RE.match(value):
        return str(raw)

    digits = value.lstrip("+-")

    if INT_RE.match(value):
        # Preserve identifier-ish values such as "007" or "0123" as text.
        if len(digits) > 1 and digits[0] == "0":
            return str(raw)
        try:
            return int(value)
        except ValueError:
            return str(raw)

    if DECIMAL_RE.match(value):
        integer_part = digits.split(".")[0].split("e")[0].split("E")[0]
        if len(integer_part) > 1 and integer_part[0] == "0":
            return str(raw)
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return str(raw)
        if math.isnan(number) or math.isinf(number):
            return str(raw)
        return number

    return str(raw)


# --------------------------------------------------------------------------- #
# Spreadsheet parsing (.xlsx / .xls)
# --------------------------------------------------------------------------- #

ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Ancient BIFF2-BIFF5 workbooks are stored without an OLE2 container.
BIFF_MAGIC = (b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08")

# Members that identify a zip container as an OOXML spreadsheet.
XLSX_MEMBERS = ("xl/workbook.xml", "xl/workbook.bin")

FORMAT_CSV = "csv"
FORMAT_XLSX = "xlsx"
FORMAT_XLS = "xls"


def detect_format(data: bytes) -> str:
    """Classify raw bytes as `csv`, `xlsx` or `xls` from their signature.

    The signature wins over the file name: a `.csv` that really holds a
    workbook (or the reverse) is still ingested correctly.
    """
    if data.startswith(ZIP_MAGIC):
        return FORMAT_XLSX
    if data.startswith(OLE2_MAGIC) or data.startswith(BIFF_MAGIC):
        return FORMAT_XLS
    return FORMAT_CSV


def excel_datetime(value) -> str:
    """Render a date/time cell deterministically as ISO 8601 text."""
    if isinstance(value, datetime.datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    return str(value)


def spreadsheet_value(value):
    """Normalise one worksheet cell into a JSON-serialisable value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time,
                          datetime.timedelta)):
        return excel_datetime(value)
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = value.decode("latin-1")
    # Text cells go through the same coercion as CSV so that both ingestion
    # paths produce identical types for identical content.
    return coerce_value(value)


def cell_is_blank(value) -> bool:
    return value == "" or value is None


def grid_to_table(grid: list[list]) -> tuple[list[str], list[list]]:
    """Turn a rectangular worksheet grid into (columns, rows).

    The first non-blank row is the header; column order is the worksheet's own.
    """
    rows = [row for row in grid if not all(cell_is_blank(c) for c in row)]
    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: the first worksheet must have a header row "
            "and at least one data row."
        )

    header = list(rows[0])
    while header and cell_is_blank(header[-1]):
        header.pop()
    if not header:
        raise BadRequest("Non-tabular content: the worksheet header row is empty.")

    columns = normalise_columns([
        "" if cell_is_blank(cell) else str(cell) for cell in header
    ])
    width = len(columns)

    data_rows: list[list] = []
    for raw_row in rows[1:]:
        cells = list(raw_row[:width])
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        data_rows.append(cells)

    if not data_rows:
        raise BadRequest(
            "Non-tabular content: the first worksheet must have a header row "
            "and at least one data row."
        )
    return columns, data_rows


def parse_xlsx(data: bytes) -> tuple[list[str], list[list]]:
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - dependency is declared
        raise BadRequest("Unsupported format: .xlsx support is unavailable.")

    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise BadRequest("Unsupported format: the content is not a readable workbook.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        raise BadRequest("Unsupported format: the content is not a readable workbook.")
    if not any(member in names for member in XLSX_MEMBERS):
        raise BadRequest("Unsupported format: the content is not a spreadsheet file.")

    workbook = None
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
        sheets = workbook.worksheets
        if not sheets:
            raise BadRequest("Non-tabular content: the workbook has no worksheets.")
        # Only the first worksheet is ingested.
        grid = [
            [spreadsheet_value(cell) for cell in row]
            for row in sheets[0].iter_rows(values_only=True)
        ]
    except DataGateError:
        raise
    except Exception as exc:
        raise BadRequest(f"Unsupported format: cannot read the workbook ({exc}).")
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:  # pragma: no cover - defensive
                pass

    return grid_to_table(grid)


def parse_xls(data: bytes) -> tuple[list[str], list[list]]:
    try:
        import xlrd
    except ImportError:  # pragma: no cover - dependency is declared
        raise BadRequest("Unsupported format: .xls support is unavailable.")

    try:
        book = xlrd.open_workbook(file_contents=data)
        if book.nsheets < 1:
            raise BadRequest("Non-tabular content: the workbook has no worksheets.")
        sheet = book.sheet_by_index(0)
        datemode = book.datemode
        grid = []
        for index in range(sheet.nrows):
            grid.append([
                xls_cell(cell, datemode) for cell in sheet.row(index)
            ])
    except DataGateError:
        raise
    except Exception as exc:
        raise BadRequest(f"Unsupported format: cannot read the workbook ({exc}).")

    return grid_to_table(grid)


def xls_cell(cell, datemode):
    import xlrd

    kind = cell.ctype
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if kind == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if kind == xlrd.XL_CELL_ERROR:
        return ""
    if kind == xlrd.XL_CELL_DATE:
        try:
            parts = xlrd.xldate_as_tuple(cell.value, datemode)
        except Exception:
            return spreadsheet_value(cell.value)
        year, month, day, hour, minute, second = parts
        if (year, month, day) == (0, 0, 0):
            return datetime.time(hour, minute, second).isoformat()
        if (hour, minute, second) == (0, 0, 0):
            return datetime.date(year, month, day).isoformat()
        return datetime.datetime(year, month, day, hour, minute,
                                 second).isoformat(sep=" ")
    return spreadsheet_value(cell.value)


# --------------------------------------------------------------------------- #
# Ingestion (format dispatch)
# --------------------------------------------------------------------------- #


def ingest_bytes(data: bytes,
                 charset: str | None = None) -> tuple[list[str], list[list]]:
    """Turn raw source bytes into (columns, rows) for any supported format."""
    if not data or not data.strip():
        raise BadRequest("Non-tabular content: the source is empty.")

    # `charset` is only meaningful for text CSV; it is validated either way so
    # that a bogus name is reported rather than silently ignored.
    if charset is not None:
        validate_charset(charset)

    fmt = detect_format(data)
    if fmt == FORMAT_XLSX:
        return parse_xlsx(data)
    if fmt == FORMAT_XLS:
        return parse_xls(data)

    if charset is not None:
        text = decode_with_charset(data, charset)
    else:
        if looks_binary(data):
            raise BadRequest(
                "Unsupported format: the source is binary data in no supported "
                "format (CSV, .xls, .xlsx)."
            )
        text = detect_decode(data)
    return parse_csv(text)


# --------------------------------------------------------------------------- #
# Response controls (pagination, sorting, shape)
# --------------------------------------------------------------------------- #

CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc",
                  "_rowid", "_total")

SHAPES = ("lists", "objects")


def single_value(args, name: str) -> str | None:
    """Return the single value for `name`, or None when absent.

    A control parameter repeated in the query string is a bad request.
    """
    values = args.getlist(name)
    if not values:
        return None
    if len(values) > 1:
        raise BadRequest(
            f"Invalid {name}: parameter may only be supplied once "
            f"({len(values)} values given)."
        )
    return values[0]


def parse_presence_flag(args, name: str) -> bool:
    """True when `name` is present in the query string at all.

    The value is irrelevant (`?force`, `?force=`, `?force=1` all count), but a
    second occurrence is a bad request.
    """
    values = args.getlist(name)
    if not values:
        return False
    if len(values) > 1:
        raise BadRequest(
            f"Invalid {name}: the flag may only be supplied once "
            f"({len(values)} values given)."
        )
    return True


def parse_int_param(raw: str, name: str, minimum: int) -> int:
    text = (raw or "").strip()
    kind = "a positive integer" if minimum > 0 else "a non-negative integer"
    if not text or not re.fullmatch(r"[+-]?\d+", text):
        raise BadRequest(f"Invalid {name}: expected {kind}, got {raw!r}.")
    try:
        value = int(text)
    except ValueError:  # pragma: no cover - guarded by the regex above
        raise BadRequest(f"Invalid {name}: expected {kind}, got {raw!r}.")
    if value < minimum:
        raise BadRequest(f"Invalid {name}: expected {kind}, got {raw!r}.")
    return value


def parse_toggle(args, name: str) -> bool:
    """`_rowid`/`_total` accept only the literal value 'hide'."""
    raw = single_value(args, name)
    if raw is None:
        return False
    if raw.strip() != "hide":
        raise BadRequest(f"Invalid {name}: the only supported value is 'hide', "
                         f"got {raw!r}.")
    return True


def parse_shape(args) -> str:
    raw = single_value(args, "_shape")
    if raw is None:
        return "lists"
    shape = raw.strip()
    if shape not in SHAPES:
        raise BadRequest(
            f"Invalid _shape: expected one of {', '.join(SHAPES)}, got {raw!r}."
        )
    return shape


def parse_sort(args, columns: list[str]):
    """Return (column, descending) or (None, False) when unsorted."""
    chosen = None
    for name in ("_sort", "_sort_desc"):
        raw = single_value(args, name)
        if raw is None:
            continue
        column = raw.strip()
        if not column:
            raise BadRequest(f"Invalid {name}: a column name is required.")
        if column not in columns:
            raise BadRequest(f"Invalid {name}: unknown column {raw!r}.")
        # `_sort_desc` is checked last, so it wins when both are present.
        chosen = (column, name == "_sort_desc")
    return chosen if chosen is not None else (None, False)


def sort_key(value):
    """Order values deterministically across mixed types: blanks, numbers, text."""
    if value is None:
        return (0, 0, "")
    if isinstance(value, bool):
        return (1, int(value), "")
    if isinstance(value, (int, float)):
        return (1, value, "")
    text = str(value)
    if not text.strip():
        return (0, 0, "")
    return (2, 0, text)


# --------------------------------------------------------------------------- #
# Column-level filtering
# --------------------------------------------------------------------------- #

# Filters are written `<column>__<comparator>=<value>`; the comparator is the
# part after the *last* separator so that columns containing `__` still work.
FILTER_SEPARATOR = "__"

COMPARATORS = ("exact", "contains", "less", "greater")

NUMERIC_COMPARATORS = ("less", "greater")


def filter_text(value) -> str:
    """Render a stored cell the way `exact`/`contains` compare it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def filter_number(value):
    """Parse a stored cell or filter value as a float, or None when not numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_filters(args, columns: list[str]) -> list[tuple]:
    """Validate `<column>__<comparator>=<value>` params into matcher tuples.

    Control parameters (`_`-prefixed) and params without the separator are not
    filters and are ignored here.
    """
    filters: list[tuple] = []
    for key in args.keys():
        if key.startswith("_") or FILTER_SEPARATOR not in key:
            continue

        values = args.getlist(key)
        if len(values) > 1:
            raise BadRequest(
                f"Invalid filter {key!r}: duplicate filter key "
                f"({len(values)} values given)."
            )

        column, _, comparator = key.rpartition(FILTER_SEPARATOR)
        if comparator not in COMPARATORS:
            raise BadRequest(
                f"Invalid filter {key!r}: unknown comparator {comparator!r}, "
                f"expected one of {', '.join(COMPARATORS)}."
            )
        if column not in columns:
            raise BadRequest(f"Invalid filter {key!r}: unknown column {column!r}.")

        raw = values[0]
        number = None
        if comparator in NUMERIC_COMPARATORS:
            number = filter_number(raw)
            if number is None:
                raise BadRequest(
                    f"Invalid filter {key!r}: __{comparator} requires a numeric "
                    f"value, got {raw!r}."
                )
        filters.append((columns.index(column), comparator, raw, number))
    return filters


def row_matches(row: list, filters: list[tuple]) -> bool:
    """True when `row` satisfies every filter (filters are ANDed)."""
    for index, comparator, raw, number in filters:
        value = row[index] if index < len(row) else ""
        if comparator == "exact":
            if filter_text(value) != raw:
                return False
        elif comparator == "contains":
            if raw not in filter_text(value):
                return False
        else:
            # Rows whose stored value is not numeric never match.
            stored = filter_number(value)
            if stored is None:
                return False
            if comparator == "less":
                if not stored < number:
                    return False
            elif not stored > number:
                return False
    return True


def check_deadline(deadline: float) -> None:
    if time.perf_counter() > deadline:
        raise QueryTimeout()


def apply_filters(numbered: list[tuple], filters: list[tuple],
                  deadline: float) -> list[tuple]:
    check_deadline(deadline)
    if not filters:
        return numbered
    selected = []
    for position, item in enumerate(numbered):
        if position % TIMEOUT_CHECK_INTERVAL == 0:
            check_deadline(deadline)
        if row_matches(item[1], filters):
            selected.append(item)
    check_deadline(deadline)
    return selected


# --------------------------------------------------------------------------- #
# Query evaluation (shared by /datasets/<id> and /datasets/<id>/export)
# --------------------------------------------------------------------------- #


class Query:
    """The outcome of applying filters, sorting and pagination to a dataset."""

    def __init__(self, columns, window, total, shape, hide_rowid, hide_total):
        self.columns = columns
        self.window = window          # [(rowid, [values...]), ...]
        self.total = total            # matching rows before pagination
        self.shape = shape
        self.hide_rowid = hide_rowid
        self.hide_total = hide_total


def evaluate_query(record: dict, args, started: float) -> Query:
    """Run `filter -> sort -> paginate` for a stored dataset.

    The order is fixed so that both the JSON and the CSV views of a dataset
    always agree, row for row.
    """
    columns = list(record["columns"])

    for name in CONTROL_PARAMS:
        single_value(args, name)

    shape = parse_shape(args)
    hide_rowid = parse_toggle(args, "_rowid")
    hide_total = parse_toggle(args, "_total")

    raw_size = single_value(args, "_size")
    size = DEFAULT_ROW_LIMIT if raw_size is None else parse_int_param(raw_size, "_size", 1)

    raw_offset = single_value(args, "_offset")
    offset = 0 if raw_offset is None else parse_int_param(raw_offset, "_offset", 0)

    sort_column, descending = parse_sort(args, columns)
    filters = parse_filters(args, columns)

    # Rows are stored with their 1-based source position so that `rowid`
    # survives filtering, sorting and pagination.
    deadline = started + QUERY_TIMEOUT_SECONDS
    numbered = list(enumerate(record["rows"], start=1))

    # Filter first, then sort, then paginate; `total` is the filtered count
    # before pagination.
    numbered = apply_filters(numbered, filters, deadline)
    total = len(numbered)

    if sort_column is not None:
        index = columns.index(sort_column)
        numbered.sort(key=lambda item: sort_key(item[1][index]), reverse=descending)
        check_deadline(deadline)

    window = numbered[offset:offset + size]
    return Query(columns, window, total, shape, hide_rowid, hide_total)


def render_csv(columns: list[str], window: list[tuple]) -> bytes:
    """Serialise a query window as RFC 4180-style CSV in source column order."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=",", quotechar='"',
                        quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(list(columns))
    for _, values in window:
        writer.writerow([filter_text(value) for value in values])
    return buffer.getvalue().encode("utf-8")


def safe_filename(name: str) -> str:
    """Make `name` safe to place inside a quoted Content-Disposition value."""
    cleaned = "".join(ch for ch in str(name) if ch.isalnum() or ch in "-_.")
    return cleaned or "dataset"


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #

UPLOAD_FIELDS = ("file", "attachment")

MALFORMED_UPLOAD = ("Malformed multipart request: the form data could not be "
                    "parsed.")


def is_multipart(req) -> bool:
    mimetype = (req.mimetype or "").lower()
    return mimetype.startswith("multipart/")


def read_upload(req) -> tuple[bytes, str]:
    """Return (bytes, filename) for the `file` or `attachment` part."""
    try:
        files = req.files
        form = req.form
    except DataGateError:
        raise
    except Exception:
        raise BadRequest(MALFORMED_UPLOAD)

    for field in UPLOAD_FIELDS:
        storage = files.get(field)
        if storage is None:
            continue
        try:
            data = storage.read()
        except Exception:
            raise BadRequest(MALFORMED_UPLOAD)
        return data, (storage.filename or "")

    # Some clients send the payload as a plain (non-file) part.
    for field in UPLOAD_FIELDS:
        if field in form:
            return form[field].encode("utf-8", errors="replace"), ""

    raise BadRequest(
        "Missing file field: the multipart form must include a 'file' or "
        "'attachment' part."
    )


# --------------------------------------------------------------------------- #
# Flask application
# --------------------------------------------------------------------------- #


def add_cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES
    # Uploaded payloads may also arrive as ordinary (non-file) form parts.
    app.config["MAX_FORM_MEMORY_SIZE"] = MAX_BYTES

    def error(message: str, status: int):
        return jsonify({"ok": False, "error": message}), status

    @app.before_request
    def _start_timer():
        g.started_at = time.perf_counter()

    @app.after_request
    def _cors(response: Response):
        return add_cors(response)

    @app.route("/convert", methods=["GET", "HEAD", "OPTIONS"])
    def convert():
        if request.method == "OPTIONS":
            return Response(status=204)

        if "source" not in request.args:
            return error("Query parameter 'source' is required.", 400)

        try:
            source_raw = request.args.get("source", "")
            source = validate_url(source_raw)

            # `force` is a presence flag: the value (if any) does not matter,
            # but supplying it more than once is a bad request.
            force = parse_presence_flag(request.args, "force")

            charset = None
            if "charset" in request.args:
                charset = request.args.get("charset", "")
                validate_charset(charset)

            dataset_id = dataset_id_for(source_raw)
            key = cache_key_for(source_raw, charset)

            if CACHE_ENABLED and not force:
                cached = load_dataset(dataset_id)
                if cached is not None and cached.get("cache_key") == key:
                    # A cache hit answers exactly like a fresh parse.
                    return jsonify({"ok": True,
                                    "endpoint": f"/datasets/{dataset_id}"}), 200

            # Re-ingestion only replaces the stored dataset once it succeeds,
            # so a failed (forced) refresh leaves the previous data queryable.
            payload_bytes = fetch_source(source)
            columns, rows = ingest_bytes(payload_bytes, charset=charset)
            store_dataset(dataset_id, {"columns": columns, "rows": rows,
                                       "source": source_raw, "cache_key": key})
        except DataGateError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:  # pragma: no cover - defensive
            return error(f"Failed to convert source: {exc}", 400)

        return jsonify({"ok": True, "endpoint": f"/datasets/{dataset_id}"}), 200

    @app.route("/upload", methods=["POST", "OPTIONS"])
    def upload():
        if request.method == "OPTIONS":
            return Response(status=204)

        if not is_multipart(request):
            return error(
                "Unsupported media type: /upload requires a multipart/form-data "
                "request carrying a 'file' or 'attachment' part.",
                415,
            )

        try:
            data, filename = read_upload(request)

            charset = None
            if "charset" in request.args:
                charset = request.args.get("charset", "")
            elif "charset" in request.form:
                charset = request.form.get("charset", "")

            dataset_id = dataset_id_for_bytes(data)
            columns, rows = ingest_bytes(data, charset=charset)
            store_dataset(dataset_id, {"columns": columns, "rows": rows,
                                       "source": filename or "upload"})
        except DataGateError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:  # pragma: no cover - defensive
            return error(f"Failed to ingest the uploaded file: {exc}", 400)

        return jsonify({"ok": True, "endpoint": f"/datasets/{dataset_id}"}), 200

    @app.route("/datasets/<dataset_id>", methods=["GET", "HEAD", "OPTIONS"])
    def dataset(dataset_id: str):
        if request.method == "OPTIONS":
            return Response(status=204)

        started = getattr(g, "started_at", time.perf_counter())
        record = load_dataset(dataset_id)
        if record is None:
            return error(f"Unknown dataset id: {dataset_id!r}", 404)

        try:
            query = evaluate_query(record, request.args, started)
        except DataGateError as exc:
            return error(exc.message, exc.status)

        columns = query.columns
        if query.shape == "objects":
            rows = []
            for rowid, values in query.window:
                row = {} if query.hide_rowid else {"rowid": rowid}
                for column, value in zip(columns, values):
                    row[column] = value
                rows.append(row)
        else:
            rows = [list(values) for _, values in query.window]

        query_ms = max(0.0, round((time.perf_counter() - started) * 1000.0, 3))

        payload = {"ok": True, "columns": columns, "rows": rows}
        if not query.hide_total:
            payload["total"] = query.total
        payload["query_ms"] = query_ms
        return jsonify(payload), 200

    @app.route("/datasets/<dataset_id>/export", methods=["GET", "HEAD", "OPTIONS"])
    def export(dataset_id: str):
        if request.method == "OPTIONS":
            return Response(status=204)

        started = getattr(g, "started_at", time.perf_counter())
        record = load_dataset(dataset_id)
        if record is None:
            return error(f"Unknown dataset id: {dataset_id!r}", 404)

        try:
            # `_shape`, `_rowid` and `_total` are accepted but never change the
            # CSV: it is always the source columns followed by the row window.
            query = evaluate_query(record, request.args, started)
        except DataGateError as exc:
            return error(exc.message, exc.status)

        body = render_csv(query.columns, query.window)
        response = Response(body, status=200)
        response.headers["Content-Type"] = "text/csv"
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{safe_filename(dataset_id)}.csv"'
        )
        return response

    @app.route("/", methods=["GET", "HEAD", "OPTIONS"])
    def index():
        if request.method == "OPTIONS":
            return Response(status=204)
        return jsonify({
            "ok": True,
            "service": "datagate",
            "endpoints": [
                "/convert?source=<url>[&charset=<name>][&force]",
                "/upload (POST multipart, field 'file' or 'attachment')",
                "/datasets/<id>",
                "/datasets/<id>/export",
            ],
            "formats": ["csv", "xls", "xlsx"],
            "cache_enabled": CACHE_ENABLED,
            "controls": list(CONTROL_PARAMS),
            "filters": [f"<column>__{name}=<value>" for name in COMPARATORS],
        }), 200

    @app.errorhandler(HTTPException)
    def _json_errors(exc):
        status = getattr(exc, "code", 500) or 500
        if status in (404, 405):
            status, message = 404, "Not found."
        elif status == 400:
            message = "Bad request."
        elif status == 413:
            message = "Payload too large: the upload exceeds the size limit."
        elif status == 415:
            message = ("Unsupported media type: /upload requires a "
                       "multipart/form-data request.")
        elif status >= 500:
            message = "Internal server error."
        else:
            message = getattr(exc, "description", None) or "Request failed."
        return error(message, status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        if isinstance(exc, DataGateError):
            return error(exc.message, exc.status)
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            return _json_errors(exc)
        return error(f"Internal server error: {exc}", 500)

    return app


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="datagate", description="datagate server")
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="Start the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)

    if not argv or argv[0].startswith("-"):
        argv = ["start"] + argv

    args = parser.parse_args(argv)
    if args.command != "start":
        parser.print_help()
        return 1

    app = create_app()
    app.run(host=args.address, port=args.port, threaded=True, debug=False,
            use_reloader=False)
    return 0


app = create_app()

if __name__ == "__main__":
    raise SystemExit(main())

"""datagate - convert remote CSV files into queryable JSON datasets.

Usage:
    python datagate.py start --port <port> --address <address>

Environment:
    CACHE_ENABLED  1/true/yes/on (the default) or 0/false/no/off.  Any other
                   value is rejected and the server refuses to start.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import zipfile
from decimal import Decimal
from urllib.parse import urlsplit

import openpyxl
import requests
import xlrd
from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_ROW_LIMIT = 100

# Control parameters accepted by /datasets/<id>.  Each may appear at most once.
CONTROL_PARAMS = (
    "_size",
    "_offset",
    "_shape",
    "_sort",
    "_sort_desc",
    "_rowid",
    "_total",
    "_timeout",
)

VALID_SHAPES = ("lists", "objects")

FETCH_TIMEOUT = 30
QUERY_TIMEOUT_MS = 15000
MAX_BYTES = 64 * 1024 * 1024
SNIFF_ROWS = 200

CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]

# --------------------------------------------------------------------------
# Cache configuration
# --------------------------------------------------------------------------

CACHE_ENV_VAR = "CACHE_ENABLED"

# Strict, case-insensitive spellings.  Nothing else is accepted - not the
# empty string, not surrounding whitespace, not "TRUE!" - so that a typo in
# the environment is reported instead of silently changing behaviour.
CACHE_TRUE_VALUES = ("1", "true", "yes", "on")
CACHE_FALSE_VALUES = ("0", "false", "no", "off")

# Caching is on unless the environment says otherwise; main() re-reads the
# variable strictly so an invalid value fails startup.
CACHE_ENABLED = True


def parse_cache_enabled(raw):
    """Interpret a CACHE_ENABLED value, raising ValueError when unrecognised."""
    if raw is None:
        return True
    value = raw.lower()
    if value in CACHE_TRUE_VALUES:
        return True
    if value in CACHE_FALSE_VALUES:
        return False
    raise ValueError(
        "invalid %s value %r: expected one of %s"
        % (
            CACHE_ENV_VAR,
            raw,
            ", ".join(CACHE_TRUE_VALUES + CACHE_FALSE_VALUES),
        )
    )


def configure_cache_from_env(environ=None):
    """Apply CACHE_ENABLED from the environment. Raises ValueError if invalid."""
    global CACHE_ENABLED
    env = os.environ if environ is None else environ
    CACHE_ENABLED = parse_cache_enabled(env.get(CACHE_ENV_VAR))
    return CACHE_ENABLED


try:
    configure_cache_from_env()
except ValueError:
    # Importing the module must not explode; main() turns the same invalid
    # value into a startup failure with a message on stderr.
    CACHE_ENABLED = True

# --------------------------------------------------------------------------
# Dataset store
# --------------------------------------------------------------------------

_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()


def dataset_id(source: str) -> str:
    """Deterministic id derived only from the source URL string."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def content_id(data: bytes) -> str:
    """Deterministic id derived only from the uploaded bytes.

    Uploads have no URL to key on, so identical bytes must land on the same
    dataset however they were named or submitted.
    """
    return hashlib.sha256(data).hexdigest()[:16]


def store_dataset(
    ds_id: str, columns: list, rows: list, rowids: list, texts: list
) -> None:
    with _STORE_LOCK:
        _STORE[ds_id] = {
            "columns": columns,
            "rows": rows,
            "rowids": rowids,
            "texts": texts,
        }


def get_dataset(ds_id: str):
    with _STORE_LOCK:
        return _STORE.get(ds_id)


# Bytes previously fetched for a source, keyed by the dataset id that source
# maps to.  Holding the body (rather than only the parsed rows) lets a repeat
# request with a different charset be answered without going back to the
# network, while still parsing exactly as a fresh request would.
_SOURCE_CACHE: dict[str, dict] = {}


def cache_source(ds_id: str, body: bytes, charset_key) -> None:
    with _STORE_LOCK:
        _SOURCE_CACHE[ds_id] = {"body": body, "charset": charset_key}


def cached_source(ds_id: str):
    """The cached body for ``ds_id``, or None when there is nothing to reuse."""
    with _STORE_LOCK:
        entry = _SOURCE_CACHE.get(ds_id)
        # A cache entry is only usable while the dataset it produced is still
        # stored, since /convert answers with that dataset's endpoint.
        if entry is None or ds_id not in _STORE:
            return None
        return entry


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class DataGateError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------------
# URL validation
# --------------------------------------------------------------------------


def validate_source(source: str) -> str:
    """Validate the source URL string, raising a 400 error when malformed."""
    if source is None:
        raise DataGateError(400, "Missing required query parameter: source")

    candidate = source.strip()
    if not candidate:
        raise DataGateError(400, "Invalid URL: source must not be empty")

    try:
        parts = urlsplit(candidate)
    except ValueError:
        raise DataGateError(400, "Invalid URL: %r could not be parsed" % source)

    scheme = parts.scheme.lower()
    if not scheme:
        raise DataGateError(400, "Invalid URL: missing scheme in %r" % source)
    if scheme not in ("http", "https"):
        raise DataGateError(400, "Invalid URL: unsupported scheme %r" % parts.scheme)

    try:
        hostname = parts.hostname
    except ValueError:
        raise DataGateError(400, "Invalid URL: malformed host in %r" % source)
    if not parts.netloc or not hostname:
        raise DataGateError(400, "Invalid URL: missing host in %r" % source)

    try:
        if parts.port is not None and not (0 < parts.port < 65536):
            raise ValueError
    except ValueError:
        raise DataGateError(400, "Invalid URL: malformed port in %r" % source)

    if any(ch in candidate for ch in (" ", "\t", "\n", "\r")):
        raise DataGateError(400, "Invalid URL: whitespace is not allowed in %r" % source)

    return candidate


# --------------------------------------------------------------------------
# Charset handling
# --------------------------------------------------------------------------


def validate_charset(charset: str) -> str:
    """Ensure the requested charset names a usable text codec."""
    if charset is None:
        return None

    name = charset.strip()
    if not name:
        raise DataGateError(400, "Unsupported or malformed charset: %r" % charset)

    try:
        codecs.lookup(name)
        probe = b"datagate".decode(name)
    except (LookupError, TypeError, ValueError, UnicodeDecodeError):
        raise DataGateError(400, "Unsupported or malformed charset: %r" % charset)
    if not isinstance(probe, str):
        raise DataGateError(400, "Unsupported or malformed charset: %r" % charset)
    return name


BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]


def detect_encoding(data: bytes) -> str:
    """Detect an unambiguous encoding from the content, else fall back to latin-1."""
    for bom, name in BOMS:
        if data.startswith(bom):
            try:
                data.decode(name)
                return name
            except UnicodeDecodeError:
                break

    # UTF-16/32 without a BOM leave a distinctive NUL pattern.
    if b"\x00" in data:
        for name in ("utf-32-le", "utf-32-be", "utf-16-le", "utf-16-be"):
            try:
                text = data.decode(name)
            except (UnicodeDecodeError, UnicodeError, ValueError):
                continue
            if "\x00" not in text and text.strip():
                return name

    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    return "latin-1"


def decode_body(data: bytes, charset: str) -> str:
    """Decode the fetched bytes, using the caller supplied charset when given."""
    if charset is not None:
        try:
            text = data.decode(charset)
        except (UnicodeDecodeError, LookupError, TypeError, ValueError):
            raise DataGateError(
                400,
                "Unsupported or malformed charset: %r cannot decode the source content"
                % charset,
            )
    else:
        text = data.decode(detect_encoding(data), errors="replace")

    if text.startswith("﻿"):
        text = text[1:]
    return text


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def fetch(source: str) -> bytes:
    try:
        response = requests.get(
            source,
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
        )
    except (requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema,
            requests.exceptions.InvalidURL,
            requests.exceptions.URLRequired):
        raise DataGateError(400, "Invalid URL: %r" % source)
    except requests.exceptions.RequestException as exc:
        raise DataGateError(404, "Source unreachable: %s" % exc.__class__.__name__)
    except Exception as exc:  # pragma: no cover - defensive
        raise DataGateError(404, "Source unreachable: %s" % exc.__class__.__name__)

    if response.status_code >= 400:
        raise DataGateError(
            404, "Remote HTTP error %d for source" % response.status_code
        )

    content = response.content or b""
    if len(content) > MAX_BYTES:
        content = content[:MAX_BYTES]
    return content


# --------------------------------------------------------------------------
# Tabular parsing
# --------------------------------------------------------------------------

_HTML_START = re.compile(r"^\s*(<\?xml|<!doctype|<html|<head|<body|<\!--|<[a-zA-Z]+[\s>/])", re.I)


# Container signatures.  ZIP archives are the envelope of .xlsx, OLE2 compound
# files and bare BIFF streams are the two shapes a .xls can take.
ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
BIFF_BOF_VERSIONS = (0x00, 0x02, 0x04, 0x08)

# Binary formats that are recognisably not a supported table.
OPAQUE_MAGIC = (
    b"%PDF",
    b"\x89PNG",
    b"GIF8",
    b"\xff\xd8\xff",
    b"\x1f\x8b",
    b"BZh",
    b"\x7fELF",
    b"SQLite format 3",
    b"\xfd7zXZ",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!",
    b"OggS",
    b"\x00\x01\x00\x00",
)


def looks_xlsx(data: bytes) -> bool:
    """True when the ZIP container holds an Office spreadsheet package."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except Exception:
        return False
    if any(name.lower().endswith("xl/workbook.xml") for name in names):
        return True
    return "[Content_Types].xml" in names and any(
        name.startswith("xl/") for name in names
    )


def looks_biff(data: bytes) -> bool:
    """True for a bare BIFF stream: a Begin-Of-File record with a sane length."""
    if len(data) < 6 or data[0] != 0x09 or data[1] not in BIFF_BOF_VERSIONS:
        return False
    return int.from_bytes(data[2:4], "little") <= 16


def detect_format(data: bytes) -> str:
    """Classify raw bytes as ``xlsx``, ``xls`` or ``csv``; ``None`` when unsupported.

    Content decides the format rather than the file name, so a spreadsheet
    named ``.csv`` still ingests and mislabelled text still parses as CSV.
    Empty input is treated as CSV so it fails with the non-tabular error.
    """
    if not data:
        return "csv"
    if data.startswith(ZIP_MAGIC):
        return "xlsx" if looks_xlsx(data) else None
    if data.startswith(OLE2_MAGIC):
        return "xls"
    if looks_biff(data):
        return "xls"
    if data.startswith(OPAQUE_MAGIC):
        return None
    return "csv"


def looks_non_tabular_text(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped.strip():
        return True
    if _HTML_START.match(stripped):
        return True
    if stripped[0] in "{[":
        try:
            json.loads(text)
            return True
        except ValueError:
            pass
    # Undecodable / control-character soup.
    sample = text[:4096]
    control = sum(
        1 for ch in sample
        if (ord(ch) < 32 and ch not in "\t\r\n") or ch in ("�", "\x00")
    )
    if sample and control / len(sample) > 0.05:
        return True
    return False


def read_rows(text: str, delimiter: str, limit: int = None) -> list:
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=delimiter,
        skipinitialspace=True,
    )
    rows = []
    try:
        for row in reader:
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    except csv.Error:
        return rows
    return rows


def _significant(rows: list) -> list:
    return [r for r in rows if any(cell.strip() for cell in r)]


def score_delimiter(text: str, delimiter: str):
    """Return (consistency, ncols) for a candidate delimiter, or None."""
    rows = _significant(read_rows(text, delimiter, limit=SNIFF_ROWS))
    if len(rows) < 2:
        return None
    ncols = len(rows[0])
    if ncols < 2:
        return None
    matching = sum(1 for r in rows if len(r) == ncols)
    consistency = matching / len(rows)
    if consistency < 0.6:
        return None
    return (consistency, ncols)


def infer_delimiter(text: str):
    """Infer the delimiter used by the document, or None for single-column data."""
    best = None
    best_key = None
    for index, delimiter in enumerate(CANDIDATE_DELIMITERS):
        score = score_delimiter(text, delimiter)
        if score is None:
            continue
        # Prefer consistent layouts, then more columns, then declaration order.
        key = (score[0], score[1], -index)
        if best_key is None or key > best_key:
            best_key = key
            best = delimiter
    return best


def is_single_column_tabular(text: str) -> bool:
    """Decide whether delimiter-less content is a plausible one-column table."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) < 2:
        return False
    for line in lines[:SNIFF_ROWS]:
        if len(line) > 200:
            return False
        if len(line.split()) > 3:
            return False
    return True


def assemble_table(rows: list):
    """Build (columns, rows, rowids, texts) from ``[[(value, text), ...], ...]``.

    ``rows[0]`` is the header.  ``rowids`` are 1-based source row numbers
    counted from the header row, so the header is 1 and the first data row is
    2.  ``texts`` mirrors ``rows`` with the untouched source text of every
    cell, which column filters and CSV export use alongside the coerced value.
    """
    header = rows[0]
    columns = [text.strip() for _, text in header]
    if not columns or all(col == "" for col in columns):
        raise DataGateError(400, "Non-tabular content: missing header row")

    width = len(columns)
    data_rows = []
    data_texts = []
    rowids = []
    for number, raw in enumerate(rows[1:], start=2):
        cells = list(raw[:width])
        if len(cells) < width:
            cells.extend([("", "")] * (width - len(cells)))
        data_rows.append([value for value, _ in cells])
        data_texts.append([text for _, text in cells])
        rowids.append(number)

    if not data_rows:
        raise DataGateError(
            400,
            "Non-tabular content: a header row and at least one data row are required",
        )

    return columns, data_rows, rowids, data_texts


def parse_table(text: str):
    """Parse decoded text into (columns, rows, rowids, texts); 400 when non-tabular."""
    if looks_non_tabular_text(text):
        raise DataGateError(400, "Non-tabular content: source is not a delimited table")

    delimiter = infer_delimiter(text)
    if delimiter is None:
        if not is_single_column_tabular(text):
            raise DataGateError(
                400, "Non-tabular content: no delimiter or table structure found"
            )
        delimiter = ","

    rows = _significant(read_rows(text, delimiter))
    if len(rows) < 2:
        raise DataGateError(
            400,
            "Non-tabular content: a header row and at least one data row are required",
        )

    return assemble_table([[(coerce(cell), cell) for cell in row] for row in rows])


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------

INT_RE = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
FLOAT_RE = re.compile(
    r"^[+-]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)


def coerce(value: str):
    """Deterministically convert a raw cell into a JSON friendly value.

    Integers and decimals become JSON numbers; everything else (including
    time-like values such as ``08:30``) stays text.
    """
    if not isinstance(value, str):
        return value

    token = value.strip()
    if not token:
        return value

    if INT_RE.match(token):
        try:
            return int(token)
        except ValueError:
            return value

    if FLOAT_RE.match(token):
        try:
            number = float(token)
        except ValueError:
            return value
        if number != number or number in (float("inf"), float("-inf")):
            return value
        return number

    return value


# --------------------------------------------------------------------------
# Spreadsheet parsing (.xls / .xlsx)
# --------------------------------------------------------------------------


def sheet_cell(value):
    """Convert one spreadsheet cell into its (JSON value, source text) pair.

    Spreadsheets carry typed cells, so unlike CSV there is nothing to sniff:
    numbers, booleans and dates arrive as native objects and only genuine text
    goes through the same coercion the CSV reader applies.
    """
    if value is None:
        return ("", "")

    if isinstance(value, bool):
        return (value, "TRUE" if value else "FALSE")

    if isinstance(value, Decimal):
        value = float(value)

    if isinstance(value, int):
        return (value, str(value))

    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return ("", "")
        # Every spreadsheet number is a double; show whole ones as integers.
        if value.is_integer() and abs(value) < 2 ** 53:
            whole = int(value)
            return (whole, str(whole))
        return (value, repr(value))

    if isinstance(value, datetime.datetime):
        text = (
            value.date().isoformat()
            if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)
            else value.isoformat(sep=" ")
        )
        return (text, text)

    if isinstance(value, (datetime.date, datetime.time)):
        text = value.isoformat()
        return (text, text)

    if isinstance(value, datetime.timedelta):
        text = str(value)
        return (text, text)

    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
        return (coerce(text), text)

    text = str(value)
    return (coerce(text), text)


def read_xlsx_rows(data: bytes) -> list:
    """Native cell values of the first worksheet of an .xlsx workbook."""
    try:
        book = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
    except DataGateError:
        raise
    except Exception:
        raise DataGateError(
            400, "Unsupported format: the .xlsx workbook could not be read"
        )
    try:
        sheets = book.worksheets
        if not sheets:
            raise DataGateError(
                400, "Non-tabular content: the workbook has no worksheets"
            )
        return [list(row) for row in sheets[0].iter_rows(values_only=True)]
    except DataGateError:
        raise
    except Exception:
        raise DataGateError(
            400, "Unsupported format: the .xlsx worksheet could not be read"
        )
    finally:
        try:
            book.close()
        except Exception:
            pass


def xls_cell(cell, datemode):
    """Native Python value for one xlrd cell, matching openpyxl's conventions."""
    kind = cell.ctype
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    if kind == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if kind == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(cell.value, datemode)
        except Exception:
            return cell.value
    return cell.value


def read_xls_rows(data: bytes) -> list:
    """Native cell values of the first worksheet of a legacy .xls workbook."""
    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=False)
    except DataGateError:
        raise
    except Exception:
        raise DataGateError(
            400, "Unsupported format: the .xls workbook could not be read"
        )
    try:
        if book.nsheets < 1:
            raise DataGateError(
                400, "Non-tabular content: the workbook has no worksheets"
            )
        sheet = book.sheet_by_index(0)
        return [
            [xls_cell(cell, book.datemode) for cell in sheet.row(index)]
            for index in range(sheet.nrows)
        ]
    except DataGateError:
        raise
    except Exception:
        raise DataGateError(
            400, "Unsupported format: the .xls worksheet could not be read"
        )
    finally:
        try:
            book.release_resources()
        except Exception:
            pass


def parse_spreadsheet(data: bytes, fmt: str):
    """Parse the first worksheet into (columns, rows, rowids, texts)."""
    raw = read_xlsx_rows(data) if fmt == "xlsx" else read_xls_rows(data)

    rows = [[sheet_cell(value) for value in row] for row in raw]
    # Spreadsheets pad with formatted-but-empty cells; those are not data.
    rows = [row for row in rows if any(text.strip() for _, text in row)]
    if len(rows) < 2:
        raise DataGateError(
            400,
            "Non-tabular content: a header row and at least one data row are required",
        )

    # Trailing empty header cells are padding, not anonymous columns.
    header = list(rows[0])
    while header and not header[-1][1].strip():
        header.pop()
    if not header:
        raise DataGateError(400, "Non-tabular content: missing header row")
    rows[0] = header

    return assemble_table(rows)


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------


def ingest(data: bytes, charset_raw, charset_given: bool):
    """Turn fetched or uploaded bytes into (columns, rows, rowids, texts).

    The format is decided from the content.  ``charset`` only means anything
    for text CSV, so it is validated on that branch alone; spreadsheets carry
    their own encoding and ignore it.
    """
    fmt = detect_format(data)
    if fmt is None:
        raise DataGateError(
            400, "Unsupported format: expected CSV, .xls or .xlsx content"
        )

    if fmt == "csv":
        charset = validate_charset(charset_raw) if charset_given else None
        return parse_table(decode_body(data, charset))

    return parse_spreadsheet(data, fmt)


# --------------------------------------------------------------------------
# Query controls (pagination, sorting, response shape)
# --------------------------------------------------------------------------

INT_TOKEN_RE = re.compile(r"^[+-]?[0-9]+$")


def reject_repeated(args) -> None:
    """Every control parameter may appear at most once in the query string."""
    for name in CONTROL_PARAMS:
        if len(args.getlist(name)) > 1:
            raise DataGateError(
                400, "Repeated control parameter: %s may only be given once" % name
            )


def parse_int_param(raw: str, name: str, minimum: int, description: str) -> int:
    """Parse a control parameter that must be an integer >= ``minimum``."""
    token = raw.strip() if isinstance(raw, str) else raw
    if not token or not INT_TOKEN_RE.match(token):
        raise DataGateError(400, "Invalid %s: %r is not %s" % (name, raw, description))
    try:
        value = int(token)
    except (TypeError, ValueError):
        raise DataGateError(400, "Invalid %s: %r is not %s" % (name, raw, description))
    if value < minimum:
        raise DataGateError(400, "Invalid %s: %r is not %s" % (name, raw, description))
    return value


def parse_shape(raw: str) -> str:
    if raw is None:
        return "lists"
    if raw not in VALID_SHAPES:
        raise DataGateError(
            400,
            "Invalid _shape: %r must be one of %s" % (raw, " or ".join(VALID_SHAPES)),
        )
    return raw


def parse_hide_toggle(raw: str, name: str) -> bool:
    """``hide`` is the only accepted value for the visibility toggles."""
    if raw is None:
        return False
    if raw != "hide":
        raise DataGateError(400, "Invalid %s: %r must be 'hide'" % (name, raw))
    return True


def parse_sort_column(raw: str, name: str, columns: list) -> str:
    if raw is None:
        return None
    if not raw:
        raise DataGateError(400, "Invalid %s: a column name is required" % name)
    if raw not in columns:
        raise DataGateError(400, "Invalid %s: unknown column %r" % (name, raw))
    return raw


def sort_key(value):
    """Total ordering across the mixed value types a CSV cell can hold."""
    if isinstance(value, bool):
        return (2, 0.0, str(value))
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    if isinstance(value, str):
        return (1, 0.0, value)
    return (2, 0.0, str(value))

# --------------------------------------------------------------------------
# Column filters
# --------------------------------------------------------------------------

COMPARATORS = ("exact", "contains", "less", "greater")
NUMERIC_COMPARATORS = ("less", "greater")


def parse_number(value):
    """Parse a stored cell or a filter value with ``float`` semantics.

    Returns ``None`` when the value is not a finite number, which is how both
    rejected filter values and unmatched rows are recognised.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (TypeError, ValueError):
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def split_filter_key(key: str, columns: list):
    """Split ``column__comparator`` into its two parts.

    Column names may themselves contain ``__``, so every split point is
    considered and the longest column name that is actually known wins.
    """
    splits = [
        (key[:index], key[index + 2:])
        for index in range(len(key) - 1)
        if key[index:index + 2] == "__"
    ]
    usable = [pair for pair in splits if pair[1] in COMPARATORS]
    if not usable:
        raise DataGateError(
            400,
            "Invalid comparator: %r must be one of %s"
            % (splits[-1][1] if splits else "", ", ".join(COMPARATORS)),
        )
    known = [pair for pair in usable if pair[0] in columns]
    if not known:
        raise DataGateError(400, "Unknown filter column: %r" % usable[-1][0])
    return known[-1]


def parse_filters(args, columns: list) -> list:
    """Collect the ``column__comparator=value`` filters from the query string.

    Control parameters (names starting with ``_``) and parameters without a
    ``__`` separator are not filters and are skipped here.
    """
    filters = []
    for key, values in args.lists():
        if key.startswith("_") or "__" not in key:
            continue
        if len(values) > 1:
            raise DataGateError(
                400, "Duplicate filter key: %s may only be given once" % key
            )
        column, comparator = split_filter_key(key, columns)
        target = values[0]
        number = None
        if comparator in NUMERIC_COMPARATORS:
            number = parse_number(target)
            if number is None:
                raise DataGateError(
                    400,
                    "Invalid %s filter: %r is not numeric" % (comparator, target),
                )
        filters.append((columns.index(column), comparator, target, number))
    return filters


def cell_texts(value, text: str):
    """Textual forms of a cell: the source text plus the stored value's form."""
    if isinstance(value, str):
        return (text,)
    rendered = str(value)
    if rendered == text:
        return (text,)
    return (text, rendered)


def row_matches(values: list, texts: list, filters: list) -> bool:
    """True when the row satisfies every filter; filters are ANDed."""
    for index, comparator, target, number in filters:
        value = values[index]
        text = texts[index]
        if comparator == "exact":
            if not any(candidate == target for candidate in cell_texts(value, text)):
                return False
        elif comparator == "contains":
            if not any(target in candidate for candidate in cell_texts(value, text)):
                return False
        else:
            stored = parse_number(value)
            if stored is None:
                stored = parse_number(text)
            if stored is None:
                # Non-numeric cells never match a numeric comparator.
                return False
            if comparator == "less":
                if not stored < number:
                    return False
            elif not stored > number:
                return False
    return True


def check_deadline(deadline: float) -> None:
    """Abort the query once it has outlived its time budget."""
    if time.perf_counter() > deadline:
        raise DataGateError(
            400, "Query timeout: the query exceeded its time budget"
        )


def apply_filters(triples: list, filters: list, deadline: float) -> list:
    """Keep the rows matching every filter, checking the deadline as we scan."""
    kept = []
    for count, item in enumerate(triples):
        if count % 512 == 0:
            check_deadline(deadline)
        if row_matches(item[1], item[2], filters):
            kept.append(item)
    return kept


# --------------------------------------------------------------------------
# Flask application
# --------------------------------------------------------------------------

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False


def error_response(status: int, message: str):
    response = jsonify({"ok": False, "error": message})
    response.status_code = status
    return response


@app.after_request
def add_cors_headers(response: Response) -> Response:
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, OPTIONS"
    requested = request.headers.get("Access-Control-Request-Headers")
    response.headers["Access-Control-Allow-Headers"] = requested or "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"
    return response


@app.errorhandler(DataGateError)
def handle_datagate_error(exc: DataGateError):
    return error_response(exc.status, exc.message)


@app.errorhandler(HTTPException)
def handle_http_exception(exc: HTTPException):
    message = exc.description or exc.name
    return error_response(exc.code or 500, message)


@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):  # pragma: no cover - defensive
    return error_response(500, "Internal error: %s" % exc.__class__.__name__)


def parse_force(args) -> bool:
    """Read the ``force`` bypass flag.

    It is a presence flag: ``?force`` on its own, at most once.  Carrying a
    value - even one that looks like a boolean - is a malformed request.
    """
    values = args.getlist("force")
    if not values:
        return False
    if len(values) > 1:
        raise DataGateError(
            400, "Repeated control parameter: force may only be given once"
        )
    if values[0] != "":
        raise DataGateError(
            400,
            "Invalid force: force is a presence flag and takes no value, got %r"
            % values[0],
        )
    return True


@app.route("/convert", methods=["GET", "HEAD", "OPTIONS"])
def convert():
    if request.method == "OPTIONS":
        return ("", 204)

    # Settled before any network work so a malformed flag is a 400 rather than
    # whatever the fetch happens to report.
    force = parse_force(request.args)

    if "source" not in request.args:
        raise DataGateError(400, "Missing required query parameter: source")

    raw_source = request.args.get("source")
    source = validate_source(raw_source)
    ds_id = dataset_id(raw_source)

    charset_given = "charset" in request.args
    charset_raw = request.args.get("charset")
    charset_key = (charset_given, charset_raw)

    body = None
    if CACHE_ENABLED and not force:
        entry = cached_source(ds_id)
        if entry is not None:
            if entry["charset"] == charset_key:
                # Identical request: the stored dataset already answers it.
                return jsonify({"ok": True, "endpoint": "/datasets/%s" % ds_id})
            # Same source, different charset: reparse the cached bytes so the
            # answer matches a fresh parse without repeating the download.
            body = entry["body"]

    if body is None:
        body = fetch(source)

    # Only a successful ingest replaces what is stored, so a failed (or forced)
    # re-ingestion leaves the previous dataset queryable.
    columns, rows, rowids, texts = ingest(body, charset_raw, charset_given)
    store_dataset(ds_id, columns, rows, rowids, texts)
    if CACHE_ENABLED:
        cache_source(ds_id, body, charset_key)

    return jsonify({"ok": True, "endpoint": "/datasets/%s" % ds_id})


UPLOAD_FIELDS = ("file", "attachment")


def uploaded_bytes():
    """Read the uploaded payload from the ``file`` or ``attachment`` part.

    Werkzeug parses a malformed multipart body into empty mappings rather than
    raising, so both a broken body and a missing part surface here as 400.
    """
    try:
        files = request.files
        form = request.form
    except Exception:
        raise DataGateError(400, "Malformed multipart body")

    for field in UPLOAD_FIELDS:
        if field in files:
            storage = files[field]
            try:
                return storage.read()
            except Exception:
                raise DataGateError(400, "Malformed multipart body")
        if field in form:
            # A part sent without a filename arrives as a plain form value.
            return form[field].encode("utf-8", "surrogateescape")

    raise DataGateError(
        400,
        "Missing file field: provide a multipart %s part"
        % " or ".join(repr(name) for name in UPLOAD_FIELDS),
    )


@app.route("/upload", methods=["POST", "OPTIONS"])
def upload():
    if request.method == "OPTIONS":
        return ("", 204)

    # A non-multipart body is the wrong media type; a multipart body that will
    # not parse is a malformed request, which uploaded_bytes reports as 400.
    if not (request.mimetype or "").lower().startswith("multipart/"):
        raise DataGateError(
            415, "Unsupported Media Type: /upload requires a multipart/form-data body"
        )

    data = uploaded_bytes()
    if len(data) > MAX_BYTES:
        data = data[:MAX_BYTES]

    charset_given = "charset" in request.args
    charset_raw = request.args.get("charset")
    if not charset_given and "charset" in request.form:
        charset_given = True
        charset_raw = request.form.get("charset")

    columns, rows, rowids, texts = ingest(data, charset_raw, charset_given)

    ds_id = content_id(data)
    store_dataset(ds_id, columns, rows, rowids, texts)

    return jsonify({"ok": True, "endpoint": "/datasets/%s" % ds_id})


def load_dataset(dataset: str) -> dict:
    record = get_dataset(dataset)
    if record is None:
        raise DataGateError(404, "Unknown dataset id: %r" % dataset)
    return record


def execute_query(record: dict, args, started: float):
    """Validate the controls then filter -> sort -> paginate the dataset.

    Shared by the JSON and CSV endpoints so both honour exactly the same
    controls.  Returns ``(columns, window, total, shape, hide_rowid,
    hide_total)`` where ``window`` holds the ``(rowid, values, texts)`` triples
    of the requested page.
    """
    reject_repeated(args)

    columns = list(record["columns"])
    shape = parse_shape(args.get("_shape"))
    hide_rowid = parse_hide_toggle(args.get("_rowid"), "_rowid")
    hide_total = parse_hide_toggle(args.get("_total"), "_total")

    timeout_ms = QUERY_TIMEOUT_MS
    if "_timeout" in args:
        timeout_ms = parse_int_param(
            args.get("_timeout"), "_timeout", 0, "a non-negative integer"
        )
    deadline = started + timeout_ms / 1000.0

    size = DEFAULT_ROW_LIMIT
    if "_size" in args:
        size = parse_int_param(args.get("_size"), "_size", 1, "a positive integer")
    elif "limit" in args:  # legacy alias
        size = parse_int_param(args.get("limit"), "limit", 0, "a non-negative integer")

    offset = 0
    if "_offset" in args:
        offset = parse_int_param(
            args.get("_offset"), "_offset", 0, "a non-negative integer"
        )
    elif "offset" in args:  # legacy alias
        offset = parse_int_param(args.get("offset"), "offset", 0, "a non-negative integer")

    # Both sort parameters are validated; _sort_desc wins when both are given.
    ascending = parse_sort_column(args.get("_sort"), "_sort", columns)
    descending = parse_sort_column(args.get("_sort_desc"), "_sort_desc", columns)

    filters = parse_filters(args, columns)

    check_deadline(deadline)
    triples = list(zip(record["rowids"], record["rows"], record["texts"]))

    # Filtering precedes sorting, and ``total`` counts the filtered rows.
    if filters:
        triples = apply_filters(triples, filters, deadline)
    total = len(triples)

    sort_column = descending if descending is not None else ascending
    if sort_column is not None:
        index = columns.index(sort_column)
        triples.sort(
            key=lambda triple: sort_key(triple[1][index]),
            reverse=descending is not None,
        )
    check_deadline(deadline)

    # Pagination runs on the filtered and sorted rows.
    window = triples[offset:offset + size]

    return columns, window, total, shape, hide_rowid, hide_total


@app.route("/datasets/<dataset>", methods=["GET", "HEAD", "OPTIONS"])
def dataset_query(dataset: str):
    if request.method == "OPTIONS":
        return ("", 204)

    started = time.perf_counter()
    record = load_dataset(dataset)
    columns, window, total, shape, hide_rowid, hide_total = execute_query(
        record, request.args, started
    )

    if shape == "objects":
        rows = []
        for rowid, values, _ in window:
            row = {} if hide_rowid else {"rowid": rowid}
            for name, value in zip(columns, values):
                if name == "rowid" and not hide_rowid:
                    continue
                row[name] = value
            rows.append(row)
    else:
        rows = [list(values) for _, values, _ in window]

    query_ms = max(0.0, (time.perf_counter() - started) * 1000.0)

    payload = {"ok": True, "columns": columns, "rows": rows}
    if not hide_total:
        payload["total"] = total
    payload["query_ms"] = round(query_ms, 4)
    return jsonify(payload)


@app.route("/datasets/<dataset>/export", methods=["GET", "HEAD", "OPTIONS"])
def dataset_export(dataset: str):
    if request.method == "OPTIONS":
        return ("", 204)

    started = time.perf_counter()
    record = load_dataset(dataset)
    # ``_shape``, ``_rowid`` and ``_total`` shape the JSON envelope only; CSV is
    # always the plain header-plus-rows table, so they are validated and dropped.
    columns, window, _, _, _, _ = execute_query(record, request.args, started)

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for _, _, texts in window:
        writer.writerow(list(texts))

    response = Response(buffer.getvalue().encode("utf-8"))
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = (
        'attachment; filename="%s.csv"' % dataset
    )
    return response


@app.route("/", methods=["GET", "HEAD", "OPTIONS"])
def index():
    if request.method == "OPTIONS":
        return ("", 204)
    return jsonify(
        {
            "ok": True,
            "service": "datagate",
            "endpoints": [
                "/convert?source=<url>[&charset=<enc>]",
                "/upload[?charset=<enc>]",
                "/datasets/<id>",
                "/datasets/<id>/export",
            ],
        }
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagate", description="datagate server")
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="start the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    if args.command not in (None, "start"):
        print("unknown command: %s" % args.command, file=sys.stderr)
        return 2

    try:
        configure_cache_from_env()
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

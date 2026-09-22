#!/usr/bin/env python3
"""datagate — turn remote or uploaded CSV/XLS/XLSX files into queryable JSON."""
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
import time
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import MethodNotAllowed
from werkzeug.routing import Map

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_ROW_LIMIT = 100
FETCH_TIMEOUT = (10, 30)
DELIMITERS = [",", ";", "\t", "|"]
SNIFF_ROWS = 100

# Column filters: <column>__<comparator>=<value> on /datasets/<id>.
FILTER_SEP = "__"
COMPARATORS = ("exact", "contains", "less", "greater")
NUMERIC_COMPARATORS = ("less", "greater")
# Rows checked between two query-budget checks while filtering.
DEADLINE_EVERY = 512
DEFAULT_QUERY_TIMEOUT_MS = 5000.0

# Control parameters accepted by /datasets/<id> (pagination, sorting, shape).
CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc",
                  "_rowid", "_total")
SHAPES = ("lists", "objects")
HIDE = "hide"
# ASCII-only integer syntax for _size/_offset (see AMBIGUITIES T28).
PARAM_INT_RE = re.compile(r"^[+-]?\d+$", re.ASCII)

# Type inference (ASCII-only: no Unicode digits, no locale sensitivity).
INT_RE = re.compile(r"^[+-]?\d+$", re.ASCII)
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$", re.ASCII)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?$", re.ASCII)

# Workbook containers recognised by content, not by filename (AMBIGUITIES T51).
XLSX_MAGIC = b"PK\x03\x04"                       # zip container: .xlsx
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"     # OLE2 compound file: .xls

# Anything else starting with one of these is an unrecognised format (400).
BINARY_MAGIC = (
    b"\x89PNG", b"GIF8", b"\xff\xd8\xff", b"%PDF",
    b"\x1f\x8b", b"\x7fELF", b"BM", b"Rar!",
    b"SQLite format 3", b"\xfd7zXZ", b"OggS", b"RIFF",
)

NON_TABULAR = ("Non-tabular content: a valid file needs a header row and at "
               "least one data row.")

# Cache controls. `CACHE_ENABLED` takes a strict, case-insensitive vocabulary;
# `force` is a presence flag on /convert (see AMBIGUITIES T59-T64).
CACHE_TRUE_VALUES = ("1", "true", "yes", "on")
CACHE_FALSE_VALUES = ("0", "false", "no", "off")
FORCE_PARAM = "force"

# Parsed datasets, keyed by dataset id. This doubles as the /convert cache:
# an id already present is a hit (see AMBIGUITIES T65/T72).
DATASETS = {}


def query_timeout_ms():
    """Wall-clock budget for one /datasets/<id> query (see AMBIGUITIES T36)."""
    raw = os.environ.get("DATAGATE_QUERY_TIMEOUT_MS")
    if raw is None:
        return DEFAULT_QUERY_TIMEOUT_MS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_QUERY_TIMEOUT_MS
    return value if value >= 0 else DEFAULT_QUERY_TIMEOUT_MS


QUERY_TIMEOUT_MS = query_timeout_ms()


class ConfigError(Exception):
    """A configuration value that cannot be used; reported at startup."""


# --------------------------------------------------------------------------
# Configuration: built-in defaults < DATAGATE_CONFIG file < environment (T74).
# --------------------------------------------------------------------------
CONFIG_ENV = "DATAGATE_CONFIG"
SETTING_NAMES = ("MAX_SOURCE_SIZE", "ORIGIN_ALLOWLIST", "REQUIRE_TLS",
                 "STORAGE_DIR", "CACHE_ENABLED")
# Booleans are strict: only these spellings, case-folded and trimmed (T63).
BOOL_TRUE = ("1", "true", "yes", "on")
BOOL_FALSE = ("0", "false", "no", "off")
# `integer bytes`: plain decimal, no units, no sign but `+` (see AMBIGUITIES T82).
SIZE_RE = re.compile(r"^\+?\d+$", re.ASCII)
COMMENT_PREFIX = "#"
# Built-in default store: implementation-defined, stable across restarts (T94).
DEFAULT_STORAGE_DIR = os.path.join(os.getcwd(), "datagate-data")
# Dataset ids we are willing to turn into a filename (no path traversal).
STORED_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$", re.ASCII)


def parse_bool(name, raw):
    """Strict boolean vocabulary, case-insensitive and trimmed."""
    value = raw.strip().lower()
    if value in BOOL_TRUE:
        return True
    if value in BOOL_FALSE:
        return False
    raise ConfigError(
        "%s: invalid boolean %r (expected one of %s)."
        % (name, raw, ", ".join(BOOL_TRUE + BOOL_FALSE)))


def parse_size(name, raw):
    """`MAX_SOURCE_SIZE`; an empty value means unset, i.e. no max (T81)."""
    value = raw.strip()
    if not value:
        return None
    if not SIZE_RE.match(value):
        raise ConfigError(
            "%s: invalid integer byte count %r (expected a non-negative "
            "number of bytes)." % (name, raw))
    return int(value)


def parse_suffixes(name, raw):
    """A list value: comma separated, trimmed, blanks dropped (T88)."""
    entries = tuple(item.strip() for item in raw.split(",") if item.strip())
    return entries or None


def parse_path(name, raw):
    """A path setting; an empty value falls back to the built-in default."""
    return raw.strip() or DEFAULT_STORAGE_DIR


PARSERS = {
    "MAX_SOURCE_SIZE": parse_size,
    "ORIGIN_ALLOWLIST": parse_suffixes,
    "REQUIRE_TLS": parse_bool,
    "STORAGE_DIR": parse_path,
    "CACHE_ENABLED": parse_bool,
}


def default_config():
    return {"MAX_SOURCE_SIZE": None, "ORIGIN_ALLOWLIST": None,
            "REQUIRE_TLS": False, "STORAGE_DIR": DEFAULT_STORAGE_DIR,
            "CACHE_ENABLED": True}


def read_config_file(path):
    """Parse a `KEY=VALUE` config file into a dict of raw strings.

    Blank lines and lines whose first non-blank character is `#` are ignored
    (T76); anything else must contain `=` and a non-empty key (T78). Unknown
    keys are kept here and ignored by the caller (T79).
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ConfigError("%s: cannot read config file %r: %s"
                          % (CONFIG_ENV, path, exc))
    except UnicodeDecodeError as exc:
        raise ConfigError("%s: config file %r is not valid UTF-8: %s"
                          % (CONFIG_ENV, path, exc))
    values = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIX):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ConfigError(
                "%s: %s line %d: expected KEY=VALUE, got %r"
                % (CONFIG_ENV, path, number, stripped))
        values[key] = value.strip()
    return values


def load_config(environ):
    """Layer the three configuration sources; raise ConfigError on bad input."""
    config = default_config()
    layers = []
    path = (environ.get(CONFIG_ENV) or "").strip()
    if path:
        layers.append(read_config_file(path))
    layers.append({name: environ[name] for name in SETTING_NAMES
                   if name in environ})
    for layer in layers:
        for name in SETTING_NAMES:
            if name in layer:
                config[name] = PARSERS[name](name, layer[name])
    return config


def prepare_storage(path):
    """Create `STORAGE_DIR` if missing; an unusable path is a config error."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError("STORAGE_DIR: cannot create %r: %s" % (path, exc))
    if not os.path.isdir(path) or not os.access(path, os.W_OK | os.X_OK):
        raise ConfigError("STORAGE_DIR: %r is not a writable directory." % path)
    return path


try:
    CONFIG = load_config(os.environ)
    prepare_storage(CONFIG["STORAGE_DIR"])
    CONFIG_ERROR = None
except ConfigError as _exc:
    # Reported by main(), which refuses to start (see AMBIGUITIES T64).
    CONFIG, CONFIG_ERROR = default_config(), str(_exc)

MAX_SOURCE_SIZE = CONFIG["MAX_SOURCE_SIZE"]
ORIGIN_ALLOWLIST = CONFIG["ORIGIN_ALLOWLIST"]
REQUIRE_TLS = CONFIG["REQUIRE_TLS"]
STORAGE_DIR = CONFIG["STORAGE_DIR"]
CACHE_ENABLED = CONFIG["CACHE_ENABLED"]


# --------------------------------------------------------------------------
# Dataset store: memory, backed by one JSON file per dataset (T95/T97)
# --------------------------------------------------------------------------
def storage_path(ident):
    return os.path.join(STORAGE_DIR, "%s.json" % ident)


def save_dataset(ident, dataset):
    """Persist one dataset atomically; a write failure is not fatal."""
    if not STORED_ID_RE.match(ident or ""):
        return
    path = storage_path(ident)
    temporary = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"columns": dataset["columns"], "rows": dataset["rows"]},
                      handle)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def restore_dataset(ident):
    """Read a dataset written by an earlier run; None if there is none."""
    if not STORED_ID_RE.match(ident or ""):
        return None
    try:
        with open(storage_path(ident), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        # Missing, unreadable or corrupt: indistinguishable from absent (T97).
        return None
    if not isinstance(payload, dict):
        return None
    columns, rows = payload.get("columns"), payload.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    dataset = {"columns": list(columns),
               "rows": [list(row) for row in rows if isinstance(row, list)]}
    DATASETS[ident] = dataset
    return dataset


def stored_dataset(ident):
    """The dataset for `ident` from memory or from `STORAGE_DIR`, else None."""
    dataset = DATASETS.get(ident)
    if dataset is not None:
        return dataset
    return restore_dataset(ident)


def store_dataset(ident, columns, rows):
    """Record a freshly parsed dataset, in memory and on disk."""
    dataset = {"columns": columns, "rows": rows}
    DATASETS[ident] = dataset
    save_dataset(ident, dataset)
    return dataset


def check_source_size(count, what):
    """Enforce `MAX_SOURCE_SIZE`: `= limit` passes, `> limit` is a 400."""
    if MAX_SOURCE_SIZE is not None and count > MAX_SOURCE_SIZE:
        raise bad_request(
            "%s is too large: %d bytes exceeds the MAX_SOURCE_SIZE limit of "
            "%d bytes." % (what, count, MAX_SOURCE_SIZE))


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class GateError(Exception):
    """An error with a status code and a human-readable message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def bad_request(msg):
    return GateError(400, msg)


def not_found(msg):
    return GateError(404, msg)


# --------------------------------------------------------------------------
# Source URL
# --------------------------------------------------------------------------
def validate_url(source):
    """Return the URL to fetch, or raise a 400 for anything not http(s)."""
    candidate = (source or "").strip()
    if not candidate:
        raise bad_request("Query parameter 'source' is required.")
    try:
        parts = urlsplit(candidate)
    except ValueError:
        raise bad_request("Invalid URL: %r could not be parsed." % source)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise bad_request(
            "Invalid URL: 'source' must be an http or https URL, got %r." % source)
    try:
        host = parts.hostname
    except ValueError:
        host = None
    if not parts.netloc or not host:
        raise bad_request("Invalid URL: %r has no host." % source)
    return candidate


def dataset_id(source):
    """Stable id: a pure function of the source URL string (see AMBIGUITIES T1)."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def fetch(url):
    """Fetch the remote bytes; any transport/HTTP failure is a 404."""
    try:
        response = requests.get(
            url, timeout=FETCH_TIMEOUT, allow_redirects=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
        )
    except requests.RequestException as exc:
        raise not_found("Source unreachable: %s" % exc)
    if response.status_code >= 400:
        raise not_found("Remote HTTP error %d for %s" % (response.status_code, url))
    content = response.content or b""
    # The size gate runs on the bytes actually received, before any parsing
    # (see AMBIGUITIES T83/T84).
    check_source_size(len(content), "Source")
    return content


# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------
def check_charset(name):
    """Validate a user-supplied charset name; raise 400 if unusable."""
    if name is None:
        return None
    cleaned = name.strip()
    if not cleaned:
        raise bad_request("Malformed charset: charset must not be empty.")
    try:
        info = codecs.lookup(cleaned)
    except (LookupError, ValueError, TypeError):
        raise bad_request("Unsupported charset: %r is not a known encoding." % name)
    if not getattr(info, "_is_text_encoding", True):
        raise bad_request("Unsupported charset: %r is not a text encoding." % name)
    return cleaned


def strip_bom(text):
    return text[1:] if text.startswith("﻿") else text


def decode_with(raw, charset):
    """Decode using an explicitly requested charset (strict)."""
    try:
        text = raw.decode(charset, errors="strict")
    except UnicodeDecodeError as exc:
        raise bad_request(
            "Malformed charset: content could not be decoded as %r (%s)."
            % (charset, exc.reason))
    except LookupError:
        raise bad_request("Unsupported charset: %r is not a known encoding." % charset)
    return strip_bom(text)


def detect_and_decode(raw):
    """Detect the encoding of raw bytes and decode them."""
    for bom, enc in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if raw.startswith(bom):
            try:
                return strip_bom(raw.decode(enc))
            except UnicodeDecodeError:
                break
    try:
        return strip_bom(raw.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
    except Exception:
        best = None
    if best is not None:
        try:
            return strip_bom(raw.decode(best.encoding, errors="strict"))
        except (UnicodeDecodeError, LookupError):
            pass
    for fallback in ("cp1252", "latin-1"):
        try:
            return strip_bom(raw.decode(fallback, errors="strict"))
        except UnicodeDecodeError:
            continue
    raise bad_request("Malformed charset: content encoding could not be detected.")


# --------------------------------------------------------------------------
# Tabular parsing
# --------------------------------------------------------------------------
def detect_format(raw):
    """Classify bytes as 'xlsx', 'xls', 'csv', or None for an unknown format."""
    if raw.startswith(XLSX_MAGIC):
        return "xlsx"
    if raw.startswith(XLS_MAGIC):
        return "xls"
    for magic in BINARY_MAGIC:
        if raw.startswith(magic):
            return None
    return "csv"


def reject_non_tabular_text(text):
    stripped = text.strip()
    if not stripped:
        raise bad_request("Non-tabular content: source is empty.")
    if "\x00" in text:
        raise bad_request("Non-tabular content: binary payload.")
    head = stripped[:1]
    if head == "<":
        raise bad_request("Non-tabular content: looks like HTML/XML, not CSV.")
    if head in "{[":
        raise bad_request("Non-tabular content: looks like JSON, not CSV.")


def _read(text, delimiter):
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except (csv.Error, ValueError):
        return None
    return [row for row in rows if any(cell.strip() for cell in row)]


def sniff_delimiter(text):
    """Infer the delimiter; None when the content has no tabular structure."""
    best = None
    for rank, delimiter in enumerate(DELIMITERS):
        rows = _read(text, delimiter)
        if rows is None or len(rows) < 2:
            continue
        width = len(rows[0])
        if width < 2:
            continue
        sample = rows[:SNIFF_ROWS]
        consistency = sum(1 for r in sample if len(r) == width) / len(sample)
        score = (consistency, width, -rank)
        if best is None or score > best[0]:
            best = (score, delimiter)
    return best[1] if best else None


def parse_table(text):
    """Parse decoded text into (columns, rows) with inferred types."""
    reject_non_tabular_text(text)
    delimiter = sniff_delimiter(text)
    if delimiter is None:
        raise bad_request(
            "Non-tabular content: no delimiter (',', ';' or tab) could be inferred, "
            "or the file lacks a header row and at least one data row.")
    rows = _read(text, delimiter)
    if rows is None or len(rows) < 2:
        raise bad_request(NON_TABULAR)
    columns = [cell.strip() for cell in rows[0]]
    width = len(columns)
    data = []
    for row in rows[1:]:
        values = [infer_type(cell) for cell in row[:width]]
        if len(values) < width:
            values.extend([""] * (width - len(values)))
        data.append(values)
    if not data:
        raise bad_request(NON_TABULAR)
    return columns, data


def infer_type(value):
    """Deterministic, locale-independent type inference."""
    text = value.strip()
    if not text:
        return ""
    if TIME_RE.match(text) or ":" in text:
        return text
    if INT_RE.match(text):
        return int(text)
    if FLOAT_RE.match(text):
        number = float(text)
        if math.isfinite(number):
            return number
    return text


# --------------------------------------------------------------------------
# Spreadsheets (.xlsx / .xls)
# --------------------------------------------------------------------------
def blank_cell(value):
    """Is a raw spreadsheet cell empty for the purposes of layout (T54)?"""
    return value is None or (isinstance(value, str) and not value.strip())


def used_width(rows):
    """Width of the sheet once trailing all-blank columns are trimmed (T54)."""
    width = 0
    for row in rows:
        for index in range(len(row) - 1, -1, -1):
            if not blank_cell(row[index]):
                width = max(width, index + 1)
                break
    return width


def spreadsheet_cell(value):
    """Convert one native cell value to a stored value (see AMBIGUITIES T53)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, datetime.datetime):
        if value.time() == datetime.time(0, 0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    # Text cells go through the same inference the CSV path uses.
    return infer_type(str(value))


def header_cell(value):
    """The column name a header cell contributes."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    cell = spreadsheet_cell(value)
    return "" if cell == "" else str(cell)


def load_xlsx_rows(raw):
    """Rows of the first worksheet of an .xlsx workbook (AMBIGUITIES T55)."""
    try:
        import openpyxl
    except ImportError:
        raise bad_request("Unsupported format: .xlsx support is unavailable.")
    try:
        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True,
                                      data_only=True)
    except Exception as exc:
        raise bad_request("Unrecognized format: not a readable .xlsx workbook "
                          "(%s)." % exc)
    try:
        sheets = book.worksheets
        if not sheets:
            raise bad_request(NON_TABULAR)
        return [list(row) for row in sheets[0].iter_rows(values_only=True)]
    except GateError:
        raise
    except Exception as exc:
        raise bad_request("Unrecognized format: the first worksheet could not "
                          "be read (%s)." % exc)
    finally:
        try:
            book.close()
        except Exception:
            pass


def load_xls_rows(raw):
    """Rows of the first worksheet of a legacy .xls workbook."""
    try:
        import xlrd
    except ImportError:
        raise bad_request("Unsupported format: .xls support is unavailable.")
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as exc:
        raise bad_request("Unrecognized format: not a readable .xls workbook "
                          "(%s)." % exc)
    try:
        if book.nsheets < 1:
            raise bad_request(NON_TABULAR)
        sheet = book.sheet_by_index(0)
        datemode = book.datemode
        rows = []
        for index in range(sheet.nrows):
            rows.append([xls_cell(cell, datemode) for cell in sheet.row(index)])
        return rows
    except GateError:
        raise
    except Exception as exc:
        raise bad_request("Unrecognized format: the first worksheet could not "
                          "be read (%s)." % exc)


def xls_cell(cell, datemode):
    """Native value of one .xls cell; every number is stored as a float."""
    import xlrd

    kind, value = cell.ctype, cell.value
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    if kind == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    if kind == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(value, datemode)
        except Exception:
            return value
    if kind == xlrd.XL_CELL_NUMBER:
        # .xls has only floats; narrow integral values to match CSV (T53).
        return int(value) if float(value).is_integer() else value
    return value


def parse_spreadsheet(raw, kind):
    """Parse the first worksheet into (columns, rows)."""
    rows = load_xlsx_rows(raw) if kind == "xlsx" else load_xls_rows(raw)
    rows = [row for row in rows if any(not blank_cell(cell) for cell in row)]
    if len(rows) < 2:
        raise bad_request(NON_TABULAR)
    width = used_width(rows)
    if width < 1:
        raise bad_request(NON_TABULAR)
    header = [header_cell(cell) for cell in rows[0][:width]]
    header.extend([""] * (width - len(header)))
    data = []
    for row in rows[1:]:
        values = [spreadsheet_cell(cell) for cell in row[:width]]
        values.extend([""] * (width - len(values)))
        data.append(values)
    if not data:
        raise bad_request(NON_TABULAR)
    return header, data


def ingest(raw, charset):
    """Parse uploaded/fetched bytes of any accepted format into (columns, rows).

    `charset` is honoured only for text CSV sources (AMBIGUITIES T52); the
    format is decided by content, not by filename (AMBIGUITIES T51).
    """
    kind = detect_format(raw)
    if kind is None:
        raise bad_request(
            "Unrecognized format: only CSV, .xls and .xlsx are accepted.")
    if kind == "csv":
        text = decode_with(raw, charset) if charset else detect_and_decode(raw)
        return parse_table(text)
    return parse_spreadsheet(raw, kind)


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
app = Flask(__name__)
app.json.sort_keys = False
app.url_map.strict_slashes = False


def error_response(status, message):
    response = jsonify({"ok": False, "error": message})
    response.status_code = status
    return response


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def referer_host(value):
    """The hostname of a `Referer`, or None when there is none to parse (T90)."""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    try:
        host = parts.hostname
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc or not host:
        return None
    return host


def host_allowed(host):
    """Suffix match with domain-boundary rules, case-insensitive (T86/T87)."""
    candidate = host.lower().strip(".")
    for entry in ORIGIN_ALLOWLIST or ():
        suffix = entry.lower().strip(".")
        if not suffix:
            continue
        if candidate == suffix or candidate.endswith("." + suffix):
            return True
    return False


@app.before_request
def enforce_origin_allowlist():
    """Check every request before routing; no allowlist means all pass (T89)."""
    if not ORIGIN_ALLOWLIST:
        return None
    referer = request.headers.get("Referer")
    if referer is None or not referer.strip():
        return error_response(
            403, "Forbidden: this service requires a Referer header naming an "
                 "allowed origin.")
    host = referer_host(referer)
    if host is None:
        return error_response(
            403, "Forbidden: no hostname could be parsed from the Referer %r."
                 % referer)
    if not host_allowed(host):
        return error_response(
            403, "Forbidden: origin %r is not allowed by ORIGIN_ALLOWLIST."
                 % host)
    return None


@app.errorhandler(GateError)
def handle_gate_error(exc):
    return error_response(exc.status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error_response(404, "Not found: %s" % request.path)


@app.errorhandler(405)
def handle_405(exc):
    return error_response(
        405, "Method %s is not allowed on %s." % (request.method, request.path))


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, GateError):
        return handle_gate_error(exc)
    status = getattr(exc, "code", 500)
    if not isinstance(status, int):
        status = 500
    if status == 404:
        return handle_404(exc)
    if status == 405:
        return handle_405(exc)
    return error_response(status, "Internal error: %s" % exc)


def force_requested(args):
    """Is the `force` presence flag set? A repeated `force` is a 400.

    The value is never inspected (AMBIGUITIES T59); only the number of
    occurrences matters, and the check runs before any fetch so it does not
    depend on the remote being up (AMBIGUITIES T60/T67/T68).
    """
    values = args.getlist(FORCE_PARAM)
    if len(values) > 1:
        raise bad_request(
            "Query parameter 'force' is a presence flag and may appear at "
            "most once; got %d values." % len(values))
    return bool(values)


def endpoint_url(ident):
    """The `endpoint` value: relative, or absolute https when REQUIRE_TLS (T92)."""
    path = "/datasets/%s" % ident
    if REQUIRE_TLS:
        return "https://%s%s" % (request.host, path)
    return path


def convert_response(ident):
    """The /convert success body: identical for cached and fresh parses."""
    return jsonify({"ok": True, "endpoint": endpoint_url(ident)})


@app.route("/convert", methods=["GET", "OPTIONS"])
def convert():
    if request.method == "OPTIONS":
        return ("", 204)
    if "source" not in request.args:
        raise bad_request("Query parameter 'source' is required.")
    source = request.args.get("source", "")
    # Argument errors are reported even for a URL that is already cached
    # (AMBIGUITIES T66).
    charset = check_charset(request.args.get("charset"))
    url = validate_url(source)
    forced = force_requested(request.args)

    ident = dataset_id(source)
    # A dataset left by an earlier run counts as a cache hit (T95/T96).
    if CACHE_ENABLED and not forced and stored_dataset(ident) is not None:
        return convert_response(ident)

    # A failure here propagates with its usual status and envelope, leaving any
    # previously stored dataset untouched (AMBIGUITIES T69/T70).
    raw = fetch(url)
    columns, rows = ingest(raw, charset)

    store_dataset(ident, columns, rows)
    return convert_response(ident)


# --------------------------------------------------------------------------
# File upload: `POST /upload`
# --------------------------------------------------------------------------
def upload_id(raw):
    """Content-addressed id: the same bytes always map here (AMBIGUITIES T48)."""
    return hashlib.sha256(raw).hexdigest()[:16]


def uploaded_bytes():
    """The payload of the `file` (preferred) or `attachment` part.

    A non-multipart request is a 415; a body that does not parse, or one
    carrying neither field, is a 400 (AMBIGUITIES T49/T50).
    """
    media_type = (request.mimetype or "").strip().lower()
    if media_type != "multipart/form-data":
        raise GateError(
            415, "Unsupported media type %r: POST /upload requires a "
                 "multipart/form-data body." % (request.content_type or ""))
    try:
        files = request.files
        form = request.form
    except Exception as exc:
        raise bad_request("Malformed multipart body: %s" % exc)
    for field in ("file", "attachment"):
        storage = files.get(field)
        if storage is not None:
            try:
                return storage.read()
            except Exception as exc:
                raise bad_request("Malformed multipart body: %s" % exc)
        # A part named `file`/`attachment` but sent without a filename still
        # carries the payload (AMBIGUITIES T58).
        if field in form:
            return form[field].encode("utf-8")
    raise bad_request(
        "Missing file: the multipart body must contain a 'file' or "
        "'attachment' part.")


@app.route("/upload", methods=["POST", "OPTIONS"])
def upload():
    if request.method == "OPTIONS":
        return ("", 204)
    raw = uploaded_bytes()
    # The limit applies to the uploaded file, not the multipart envelope (T83).
    check_source_size(len(raw), "Upload")
    charset = check_charset(request.args.get("charset")
                            or request.form.get("charset"))
    columns, rows = ingest(raw, charset)

    ident = upload_id(raw)
    store_dataset(ident, columns, rows)
    return jsonify({"ok": True, "endpoint": endpoint_url(ident)})


# --------------------------------------------------------------------------
# Control parameters for /datasets/<id>
# --------------------------------------------------------------------------
def read_controls(args):
    """Return {name: value-or-None}; a repeated control parameter is a 400."""
    values = {}
    for name in CONTROL_PARAMS:
        found = args.getlist(name)
        if len(found) > 1:
            raise bad_request(
                "Control parameter %r was supplied %d times; it may appear at "
                "most once." % (name, len(found)))
        values[name] = found[0] if found else None
    return values


def parse_count(raw, name, minimum, default):
    """Parse _size/_offset; anything not an in-range integer is a 400 (T28)."""
    if raw is None:
        return default
    kind = ("a positive integer" if minimum > 0 else "a non-negative integer")
    if not PARAM_INT_RE.match(raw):
        raise bad_request("Invalid %s: %r is not %s." % (name, raw, kind))
    value = int(raw)
    if value < minimum:
        raise bad_request("Invalid %s: %r is not %s." % (name, raw, kind))
    return value


def parse_shape(raw):
    if raw is None:
        return "lists"
    if raw not in SHAPES:
        raise bad_request(
            "Invalid _shape: %r is not one of 'lists' or 'objects'." % raw)
    return raw


def parse_toggle(raw, name):
    """A visibility toggle is valid only with the exact value 'hide'."""
    if raw is None:
        return False
    if raw != HIDE:
        raise bad_request(
            "Invalid %s: %r is not a valid value; the only accepted value is "
            "'hide'." % (name, raw))
    return True


def resolve_sort(controls, columns):
    """Return (column_index, descending) or (None, False).

    `_sort_desc` wins when both are present, and only the winning parameter is
    validated (AMBIGUITIES T24).
    """
    for name, descending in (("_sort_desc", True), ("_sort", False)):
        raw = controls[name]
        if raw is None:
            continue
        if raw == "":
            raise bad_request(
                "Invalid %s: a column name is required." % name)
        if raw not in columns:
            raise bad_request(
                "Invalid %s: unknown column %r; known columns are %s."
                % (name, raw, ", ".join(repr(c) for c in columns) or "none"))
        return columns.index(raw), descending
    return None, False


def sort_key(value):
    """Total, type-ranked ordering: empty < numbers < text (AMBIGUITIES T23)."""
    if value is None or value == "":
        return (0, 0.0, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (1, float(value), "")
    return (2, 0.0, str(value))


# --------------------------------------------------------------------------
# Column filters for /datasets/<id>
# --------------------------------------------------------------------------
def check_deadline(deadline):
    """Abort with a 400 once the query budget is spent (AMBIGUITIES T36)."""
    if time.perf_counter() > deadline:
        raise bad_request(
            "Query timeout: the request exceeded the %g ms query budget."
            % QUERY_TIMEOUT_MS)


def to_number(value):
    """`float` parse of a stored or filter value; None when non-numeric (T37/T38)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def cell_text(value):
    """The string form a stored value is compared against (AMBIGUITIES T32)."""
    return value if isinstance(value, str) else str(value)


def parse_filters(args, columns):
    """Return [(column_index, comparator, value, number)] for the query string.

    A parameter is a filter when its name does not begin with `_` (T35) and
    contains `__`; the comparator is whatever follows the *last* `__` (T33), and
    an unrecognised comparator is a 400 rather than an ignored parameter (T34).
    """
    filters = []
    for key, values in args.lists():
        if key.startswith("_") or FILTER_SEP not in key:
            continue
        column, _, comparator = key.rpartition(FILTER_SEP)
        if comparator not in COMPARATORS:
            raise bad_request(
                "Invalid filter %r: %r is not a valid comparator; use one of "
                "%s." % (key, comparator, ", ".join(COMPARATORS)))
        if column not in columns:
            raise bad_request(
                "Invalid filter %r: unknown column %r; known columns are %s."
                % (key, column, ", ".join(repr(c) for c in columns) or "none"))
        if len(values) > 1:
            raise bad_request(
                "Duplicate filter %r: it was supplied %d times; a filter key "
                "may appear at most once." % (key, len(values)))
        value = values[0]
        number = None
        if comparator in NUMERIC_COMPARATORS:
            number = to_number(value)
            if number is None:
                raise bad_request(
                    "Invalid filter %r: %r is not numeric; %r compares numbers."
                    % (key, value, comparator))
        # Repeated header names filter on their first column (T30/T43).
        filters.append((columns.index(column), comparator, value, number))
    return filters


def matches(value, comparator, text, number):
    """Does one stored cell satisfy one filter?"""
    if comparator == "exact":
        return cell_text(value) == text
    if comparator == "contains":
        return text in cell_text(value)
    stored = to_number(value)
    if stored is None:
        # Non-numeric stored values never match a numeric comparator.
        return False
    return stored < number if comparator == "less" else stored > number


def apply_filters(numbered, filters, deadline):
    """Select the (rowid, values) pairs satisfying every filter (AND)."""
    if not filters:
        return numbered
    kept = []
    for position, pair in enumerate(numbered):
        if position % DEADLINE_EVERY == 0:
            check_deadline(deadline)
        values = pair[1]
        if all(matches(values[index], comparator, text, number)
               for index, comparator, text, number in filters):
            kept.append(pair)
    return kept


def load_dataset(dataset_id_):
    stored = stored_dataset(dataset_id_)
    if stored is None:
        raise not_found("Unknown dataset id %r." % dataset_id_)
    return stored


def run_query(stored, args, started):
    """Filter -> sort -> paginate, shared by /datasets/<id> and its export.

    Every control parameter is parsed and validated here, including the ones
    `/export` then ignores (AMBIGUITIES T46).
    """
    controls = read_controls(args)
    shape = parse_shape(controls["_shape"])
    size = parse_count(controls["_size"], "_size", 1, DEFAULT_ROW_LIMIT)
    offset = parse_count(controls["_offset"], "_offset", 0, 0)
    columns = stored["columns"]
    index, descending = resolve_sort(controls, columns)
    hide_rowid = parse_toggle(controls["_rowid"], "_rowid")
    hide_total = parse_toggle(controls["_total"], "_total")
    filters = parse_filters(args, columns)

    # rowid is the 1-based position of the row in the source data (T22); it
    # travels with the row through filtering, sorting and pagination (T41).
    numbered = list(enumerate(stored["rows"], start=1))
    deadline = started + QUERY_TIMEOUT_MS / 1000.0
    check_deadline(deadline)
    # Filtering precedes sorting; `total` counts the filtered rows.
    numbered = apply_filters(numbered, filters, deadline)
    total = len(numbered)
    if index is not None:
        # Python's sort is stable, in both directions: ties keep source order.
        numbered.sort(key=lambda pair: sort_key(pair[1][index]),
                      reverse=descending)
    check_deadline(deadline)
    # Pagination runs on the filtered+sorted rows.
    page = numbered[offset:offset + size]
    return {"columns": columns, "page": page, "total": total, "shape": shape,
            "hide_rowid": hide_rowid, "hide_total": hide_total}


@app.route("/datasets/<dataset_id_>", methods=["GET", "OPTIONS"])
def dataset(dataset_id_):
    if request.method == "OPTIONS":
        return ("", 204)
    started = time.perf_counter()
    stored = load_dataset(dataset_id_)
    result = run_query(stored, request.args, started)
    columns, page = result["columns"], result["page"]

    if result["shape"] == "objects":
        rows = []
        for rowid, values in page:
            row = {} if result["hide_rowid"] else {"rowid": rowid}
            row.update(zip(columns, values))
            rows.append(row)
    else:
        rows = [values for _, values in page]

    payload = {"ok": True, "columns": columns, "rows": rows}
    if not result["hide_total"]:
        payload["total"] = result["total"]
    query_ms = round((time.perf_counter() - started) * 1000.0, 3)
    payload["query_ms"] = max(query_ms, 0.0)
    return jsonify(payload)


# --------------------------------------------------------------------------
# CSV export: `GET /datasets/<id>/export`
# --------------------------------------------------------------------------
def csv_field(value):
    """The text one stored value contributes to a CSV field (AMBIGUITIES T56)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def csv_bytes(columns, rows):
    """Render a header row plus data rows as CSV bytes."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([csv_field(name) for name in columns])
    for values in rows:
        writer.writerow([csv_field(value) for value in values])
    return buffer.getvalue().encode("utf-8")


@app.route("/datasets/<dataset_id_>/export", methods=["GET", "OPTIONS"])
def export(dataset_id_):
    if request.method == "OPTIONS":
        return ("", 204)
    started = time.perf_counter()
    stored = load_dataset(dataset_id_)
    # Same filters, sort and pagination; _shape/_rowid/_total change nothing.
    result = run_query(stored, request.args, started)
    body = csv_bytes(result["columns"],
                     [values for _, values in result["page"]])
    response = app.response_class(body, status=200)
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = (
        'attachment; filename="%s.csv"' % dataset_id_)
    return response


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE",
                                                "PATCH", "OPTIONS", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH",
                                    "OPTIONS", "HEAD"])
def fallback(path):
    """Unknown routes are 404; a known route with a wrong method is 405 (T17)."""
    full = "/" + path
    try:
        _known_routes().match(full, method=request.method)
    except MethodNotAllowed:
        raise GateError(
            405, "Method %s is not allowed on %s." % (request.method, full))
    except Exception:
        pass
    raise not_found("Not found: %s" % full)


_KNOWN = None


def _known_routes():
    """A routing adapter holding every real route (i.e. excluding `fallback`)."""
    global _KNOWN
    if _KNOWN is None:
        rules = [rule.empty() for rule in app.url_map.iter_rules()
                 if rule.endpoint != "fallback"]
        _KNOWN = Map(rules, strict_slashes=False).bind("localhost")
    return _KNOWN


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(prog="datagate.py", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="Start the datagate HTTP server.")
    start.add_argument("--port", type=int, default=DEFAULT_PORT,
                       help="Port to listen on (default: %d)." % DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS,
                       help="Address to bind (default: %s)." % DEFAULT_ADDRESS)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["start"]
    args = build_parser().parse_args(argv)
    if args.command != "start":
        build_parser().print_help()
        return 2
    if CONFIG_ERROR:
        print(CONFIG_ERROR, file=sys.stderr)
        return 2
    app.run(host=args.address, port=args.port, threaded=True,
            debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

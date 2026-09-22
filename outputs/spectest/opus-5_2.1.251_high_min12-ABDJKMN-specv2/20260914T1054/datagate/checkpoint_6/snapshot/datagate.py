"""datagate - convert remote CSV/spreadsheet files into queryable JSON datasets.

Start with:

    python datagate.py start --port <port> --address <address>

Settings come from the built-in defaults, then the `KEY=VALUE` file named by
`DATAGATE_CONFIG`, then the environment variables `MAX_SOURCE_SIZE`,
`ORIGIN_ALLOWLIST`, `REQUIRE_TLS`, `STORAGE_DIR` and `CACHE_ENABLED` - each layer
overriding the one before it.  Invalid configuration stops the process.
"""
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
import tempfile
import time
import zipfile
from urllib.parse import urlparse

import openpyxl
import requests
import xlrd
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_SIZE = 100
DEFAULT_OFFSET = 0
DEFAULT_SHAPE = "lists"
SHAPES = ("lists", "objects")
CONTROL_PARAMS = (
    "_size",
    "_offset",
    "_shape",
    "_sort",
    "_sort_desc",
    "_rowid",
    "_total",
)
FETCH_TIMEOUT = 20

# `/convert` caches by default; `CACHE_ENABLED` is one of the five settings read once
# at startup (see AMBIGUITIES T57).  Booleans accept exactly these spellings, in any
# case and with surrounding whitespace trimmed; anything else - including an empty or
# whitespace-only value - fails startup (T58).
CACHE_ENV_VAR = "CACHE_ENABLED"
BOOL_TRUE_VALUES = ("1", "true", "yes", "on")
BOOL_FALSE_VALUES = ("0", "false", "no", "off")
CACHE_TRUE_VALUES = BOOL_TRUE_VALUES
CACHE_FALSE_VALUES = BOOL_FALSE_VALUES
DEFAULT_CACHE_ENABLED = True
CACHE_CONFIG_KEY = "DATAGATE_CACHE_ENABLED"
SETTINGS_CONFIG_KEY = "DATAGATE_SETTINGS"
# Per-request cache bypass: a presence flag, never a value (see AMBIGUITIES T60, T61).
FORCE_PARAM = "force"

# Filter comparators, matched exactly and case-sensitively.
COMPARATORS = ("exact", "contains", "less", "greater")
NUMERIC_COMPARATORS = ("less", "greater")
FILTER_SEPARATOR = "__"
# Wall-clock budget for evaluating one dataset query, in seconds.  Overridable
# via the Flask config key of the same name.  See AMBIGUITIES.md T35.
DEFAULT_QUERY_TIMEOUT = 5.0
# How often the budget is re-checked while scanning rows.
DEADLINE_CHECK_EVERY = 256

CANDIDATE_DELIMITERS = (",", ";", "\t")

# Recognised container magic.  Format is sniffed from the bytes, not from the
# file name or the remote Content-Type (see AMBIGUITIES.md T50).
ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
UPLOAD_FIELDS = ("file", "attachment")
MULTIPART_TYPE = "multipart/form-data"

NON_TABULAR_MESSAGE = (
    "Non-tabular content: a valid file needs a header row and at least one data row."
)

# Numeric literals: plain integers and plain decimals (optionally in exponent form).
# Deliberately excludes nan/inf (not valid JSON), underscores and hex (Python quirks),
# thousands separators and currency/percent signs.  See AMBIGUITIES.md T3.
_INT_RE = re.compile(r"^[+-]?\d+$")
_DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")

# CPython refuses `int(str)` beyond 4300 digits; such a cell stays text rather than 500.
MAX_INT_DIGITS = 4300

# `_size`/`_offset` accept only a plain decimal integer literal (see AMBIGUITIES T21).
_CONTROL_INT_RE = re.compile(r"^[+-]?[0-9]+$")

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


class DataGateError(Exception):
    """An error with the HTTP status the spec's error table assigns to it."""

    status = 400

    def __init__(self, message, status=None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class BadRequest(DataGateError):
    status = 400


class NotFound(DataGateError):
    status = 404


class StartupError(Exception):
    """Misconfiguration that must stop the process before it serves anything."""


# ---------------------------------------------------------- configuration ---
#
# Three layers, lowest precedence first (see AMBIGUITIES T67):
#
#   1. the built-in defaults below,
#   2. the `KEY=VALUE` file named by `DATAGATE_CONFIG`, if any,
#   3. the settings' own environment variables, spelled exactly as the table does.
#
# Each layer is validated on its own - a bad value in the file is fatal even when the
# environment goes on to override that very key - and layers merge per key, so a file
# that sets one setting leaves the other four at their defaults.

CONFIG_ENV_VAR = "DATAGATE_CONFIG"
COMMENT_PREFIX = "#"
LIST_SEPARATOR = ","
SETTING_NAMES = (
    "MAX_SOURCE_SIZE",
    "ORIGIN_ALLOWLIST",
    "REQUIRE_TLS",
    "STORAGE_DIR",
    "CACHE_ENABLED",
)
DEFAULT_SETTINGS = {
    "max_source_size": None,      # unset: no max
    "origin_allowlist": (),       # unset: every request passes
    "require_tls": False,
    "storage_dir": None,          # implementation-defined (T75)
    "cache_enabled": DEFAULT_CACHE_ENABLED,
}
# Plain decimal integers only: no units, no underscores, no hex, no exponents (T69).
_SETTING_INT_RE = re.compile(r"^[+-]?[0-9]+$")


def parse_bool_setting(name, raw):
    """Strict boolean: the eight spellings, case-insensitive and trimmed (T58)."""
    value = raw.strip().lower()
    if value in BOOL_TRUE_VALUES:
        return True
    if value in BOOL_FALSE_VALUES:
        return False
    raise StartupError(
        "%s=%r is not a valid value: use one of %s (true) or %s (false)."
        % (name, raw, "/".join(BOOL_TRUE_VALUES), "/".join(BOOL_FALSE_VALUES))
    )


def parse_size_setting(name, raw):
    """`MAX_SOURCE_SIZE` in bytes; an empty value means unset, i.e. no max (T69)."""
    value = raw.strip()
    if not value:
        return None
    if not _SETTING_INT_RE.match(value):
        raise StartupError(
            "%s=%r is not a valid value: give a whole number of bytes." % (name, raw)
        )
    number = int(value)
    if number < 0:
        raise StartupError(
            "%s=%r is not a valid value: a byte count cannot be negative."
            % (name, raw)
        )
    return number


def parse_suffix_list(raw):
    """Comma-separated domain suffixes, normalised for matching (T71).

    Entries are lower-cased and stripped of surrounding whitespace and of leading or
    trailing dots, so `.example.com`, `example.com.` and `example.com` are one entry.
    Empty entries are dropped, so an empty value means "no allowlist".
    """
    suffixes = []
    for item in raw.split(LIST_SEPARATOR):
        suffix = item.strip().strip(".").lower()
        if suffix and suffix not in suffixes:
            suffixes.append(suffix)
    return tuple(suffixes)


def parse_path_setting(raw):
    """A filesystem path; an empty value means unset."""
    value = raw.strip()
    return value or None


def parse_settings_layer(values):
    """Validate one layer's raw strings, returning only the keys it actually sets.

    Keys outside the settings table are ignored rather than fatal (T66).
    """
    settings = {}
    if "MAX_SOURCE_SIZE" in values:
        settings["max_source_size"] = parse_size_setting(
            "MAX_SOURCE_SIZE", values["MAX_SOURCE_SIZE"])
    if "ORIGIN_ALLOWLIST" in values:
        settings["origin_allowlist"] = parse_suffix_list(values["ORIGIN_ALLOWLIST"])
    if "REQUIRE_TLS" in values:
        settings["require_tls"] = parse_bool_setting(
            "REQUIRE_TLS", values["REQUIRE_TLS"])
    if "STORAGE_DIR" in values:
        settings["storage_dir"] = parse_path_setting(values["STORAGE_DIR"])
    if "CACHE_ENABLED" in values:
        settings["cache_enabled"] = parse_bool_setting(
            CACHE_ENV_VAR, values[CACHE_ENV_VAR])
    return settings


def parse_config_text(text, origin="config"):
    """Parse `KEY=VALUE` lines; blank and `#` comment lines are ignored (T66)."""
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIX):
            continue
        if "=" not in stripped:
            raise StartupError(
                "%s line %d is not a KEY=VALUE line, a comment or blank: %r"
                % (origin, number, line)
            )
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            raise StartupError(
                "%s line %d has an empty key: %r" % (origin, number, line)
            )
        values[key] = value.strip()
    return values


def read_config_file(path):
    """Read and parse the `DATAGATE_CONFIG` file; any read failure is fatal (T65)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise StartupError(
            "%s=%r could not be read: %s"
            % (CONFIG_ENV_VAR, path, exc.strerror or exc.__class__.__name__)
        )
    except UnicodeDecodeError:
        raise StartupError(
            "%s=%r could not be read: it is not valid UTF-8 text."
            % (CONFIG_ENV_VAR, path)
        )
    return parse_config_text(text, origin="%s=%s" % (CONFIG_ENV_VAR, path))


def resolve_settings(env=None):
    """Merge the three configuration sources into one validated settings mapping."""
    environment = os.environ if env is None else env
    settings = dict(DEFAULT_SETTINGS)

    path = (environment.get(CONFIG_ENV_VAR) or "").strip()
    if path:
        settings.update(parse_settings_layer(read_config_file(path)))

    direct = {name: environment[name] for name in SETTING_NAMES if name in environment}
    settings.update(parse_settings_layer(direct))
    return settings


def check_source_size(size, max_size):
    """Enforce `MAX_SOURCE_SIZE`: `= limit` passes, `> limit` is a 400."""
    if max_size is not None and size > max_size:
        raise BadRequest(
            "Source is too large: %d bytes exceeds the %d-byte limit set by "
            "MAX_SOURCE_SIZE." % (size, max_size)
        )


# ----------------------------------------------------------- access control ---

def referer_hostname(referer):
    """The hostname of a `Referer` value, lower-cased, or None if it has none."""
    try:
        parts = urlparse(referer.strip())
        host = parts.hostname
    except ValueError:  # e.g. a malformed port
        return None
    if not host:
        return None
    return host.strip().strip(".").lower()


def host_allowed(host, allowlist):
    """Suffix match on domain-label boundaries, never a bare `endswith` (T71)."""
    for suffix in allowlist:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


# --------------------------------------------------------------- storage ---

STORAGE_SUFFIX = ".json"


def ensure_storage_dir(path):
    """Create `STORAGE_DIR` if missing; an unusable path is a startup failure (T76)."""
    if not path:
        # Implementation-defined default: a private directory for this process, so an
        # unconfigured service keeps the per-process store the caching section
        # specified.  Persistence is promised only "when the same directory is
        # reused", which means a configured one (T75).
        return tempfile.mkdtemp(prefix="datagate-store-")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise StartupError(
            "STORAGE_DIR=%r could not be created: %s"
            % (path, exc.strerror or exc.__class__.__name__)
        )
    if not os.path.isdir(path):
        raise StartupError("STORAGE_DIR=%r is not a directory." % path)
    return path


class DatasetStore:
    """The dataset store, backed by one JSON file per dataset id.

    The store *is* the `/convert` cache, so reusing a directory across a restart also
    preserves cache hits (T75).  It is read once at startup; files that are not
    readable dataset records are skipped rather than fatal (T76).
    """

    def __init__(self, directory):
        self.directory = directory
        self._records = {}
        self._load()

    def _path(self, identifier):
        return os.path.join(self.directory, identifier + STORAGE_SUFFIX)

    def _load(self):
        try:
            names = sorted(os.listdir(self.directory))
        except OSError:  # pragma: no cover - the directory was just created
            return
        for name in names:
            if not name.endswith(STORAGE_SUFFIX):
                continue
            try:
                with open(os.path.join(self.directory, name), "r",
                          encoding="utf-8") as handle:
                    record = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            columns, rows = record.get("columns"), record.get("rows")
            if not isinstance(columns, list) or not isinstance(rows, list):
                continue
            self._records[name[:-len(STORAGE_SUFFIX)]] = {
                "source": record.get("source"),
                "columns": [str(column) for column in columns],
                "rows": [list(row) for row in rows],
            }

    def get(self, identifier, default=None):
        return self._records.get(identifier, default)

    def __getitem__(self, identifier):
        return self._records[identifier]

    def __contains__(self, identifier):
        return identifier in self._records

    def __len__(self):
        return len(self._records)

    def __setitem__(self, identifier, record):
        self._records[identifier] = record
        temporary = self._path(identifier) + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.replace(temporary, self._path(identifier))


# ---------------------------------------------------------------- caching ---

def parse_cache_enabled(raw):
    """Strict parse of a `CACHE_ENABLED` value: case-insensitive and trimmed (T58).

    An absent variable (``None``) keeps the documented default, caching on; an empty
    or whitespace-only one is not one of the eight spellings and fails startup.
    """
    if raw is None:
        return DEFAULT_CACHE_ENABLED
    return parse_bool_setting(CACHE_ENV_VAR, raw)


def cache_enabled_from_env(env=None):
    """Read `CACHE_ENABLED` from the process environment (raises StartupError)."""
    environment = os.environ if env is None else env
    return parse_cache_enabled(environment.get(CACHE_ENV_VAR))


def parse_force(args):
    """True when the bare `force` flag is present on the request.

    `force` carries no value: `?force` and `?force=` force re-ingestion, any other
    value is a 400, and repeating it is a 400 as well (T60, T61).
    """
    values = args.getlist(FORCE_PARAM)
    if not values:
        return False
    if len(values) > 1:
        raise BadRequest(
            "Repeated query parameter %r: it may be given at most once." % FORCE_PARAM
        )
    if values[0] != "":
        raise BadRequest(
            "Invalid %r: it is a presence flag and takes no value." % FORCE_PARAM
        )
    return True


# --------------------------------------------------------------- identity ---

def dataset_id(source):
    """Deterministic id for a source URL string (stable across processes)."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------- fetching ---

def validate_url(source):
    """Return the source URL, or raise BadRequest if it is not a fetchable URL."""
    if source is None:
        raise BadRequest("Missing required query parameter 'source'.")
    source = source.strip()
    if not source:
        raise BadRequest("Missing required query parameter 'source'.")
    try:
        parts = urlparse(source)
    except ValueError:
        raise BadRequest("Invalid URL: %r" % source)
    if parts.scheme.lower() not in ("http", "https"):
        raise BadRequest(
            "Invalid URL: 'source' must be an http:// or https:// URL."
        )
    if not parts.netloc or not parts.hostname:
        raise BadRequest("Invalid URL: 'source' has no host.")
    return source


def fetch(source, max_size=None):
    """GET the source; any transport failure or remote HTTP error is a 404.

    `max_size` is the configured `MAX_SOURCE_SIZE` in bytes, or None for no max.
    """
    try:
        response = requests.get(
            source,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise NotFound("Source unreachable: %s" % exc.__class__.__name__)
    if response.status_code >= 400:
        raise NotFound(
            "Remote HTTP error %d while fetching source." % response.status_code
        )
    content = response.content
    check_source_size(len(content), max_size)
    return content


# --------------------------------------------------------------- decoding ---

def resolve_charset(charset):
    """Validate an explicit charset name, returning its canonical codec name."""
    if charset is None:
        return None
    name = charset.strip()
    if not name:
        raise BadRequest("Unsupported or malformed charset: charset is empty.")
    try:
        return codecs.lookup(name).name
    except (LookupError, ValueError, TypeError):
        raise BadRequest("Unsupported or malformed charset: %r" % charset)


def detect_encoding(raw):
    """Pick an unambiguous encoding from the bytes themselves, else latin-1."""
    for bom, name in _BOMS:
        if raw.startswith(bom):
            return name
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "latin-1"
    return "utf-8"


def decode(raw, charset=None):
    """Decode CSV bytes using the requested charset, or a detected one."""
    encoding = charset or detect_encoding(raw)
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        raise BadRequest(
            "Unsupported or malformed charset: content could not be decoded as %r."
            % encoding
        )
    except (LookupError, ValueError):
        raise BadRequest("Unsupported or malformed charset: %r" % encoding)
    if text.startswith("﻿"):
        text = text[1:]
    return text


# ---------------------------------------------------------------- parsing ---

def _looks_non_tabular(raw, text):
    """True for content that is recognisably some other format entirely."""
    if b"\x00" in raw:
        return True
    stripped = text.lstrip()
    if not stripped:
        return True
    if stripped.startswith("<"):  # HTML / XML document
        return True
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
        except ValueError:
            pass
        else:
            return True
    sample = text[:4096]
    odd = sum(
        1
        for ch in sample
        if (ord(ch) < 32 and ch not in "\t\r\n") or 127 <= ord(ch) <= 159
    )
    return bool(sample) and odd > len(sample) * 0.05


def _read_rows(text, delimiter):
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error:
        return []


def _is_blank(row):
    """A wholly empty line - not a row whose every *field* happens to be empty."""
    return not row or (len(row) == 1 and not row[0].strip())


def infer_delimiter(text):
    """Infer the delimiter from the content itself (`,`, `;` or `\\t`)."""
    lines = [line for line in text.splitlines() if line.strip()][:50]
    sample = "\n".join(lines)
    best = None
    for index, delimiter in enumerate(CANDIDATE_DELIMITERS):
        rows = [row for row in _read_rows(sample, delimiter) if not _is_blank(row)]
        if not rows:
            continue
        width = len(rows[0])
        if width < 2:  # this delimiter does not split the header at all
            continue
        consistency = sum(1 for row in rows if len(row) == width) / len(rows)
        score = (consistency, width, -index)
        if best is None or score > best[0]:
            best = (score, delimiter)
    return best[1] if best else ","


def parse_table(text):
    """Parse decoded CSV text into (columns, rows) with inferred types."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    delimiter = infer_delimiter(normalised)
    raw_rows = [row for row in _read_rows(normalised, delimiter) if not _is_blank(row)]
    if len(raw_rows) < 2:
        raise BadRequest(
            "Non-tabular content: a valid file needs a header row and at least "
            "one data row."
        )
    columns = [cell.strip() for cell in raw_rows[0]]
    if columns and columns[0].startswith("﻿"):
        columns[0] = columns[0][1:]
    width = len(columns)
    rows = []
    for raw_row in raw_rows[1:]:
        cells = [coerce(cell) for cell in raw_row[:width]]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        rows.append(cells)
    return columns, rows


def coerce(value):
    """Infer a JSON type for one cell: number for numeric literals, else text."""
    text = value.strip()
    if not text:
        return ""
    if _INT_RE.match(text):
        if len(text) <= MAX_INT_DIGITS:
            return int(text)
        return text  # beyond CPython's int(str) limit: keep it as text
    if _DECIMAL_RE.match(text):
        number = float(text)
        if math.isfinite(number):
            return number
    return text


# ----------------------------------------------------------- spreadsheets ---

def detect_format(raw):
    """Sniff the container: 'xlsx', 'xls' or 'csv' (see AMBIGUITIES T50)."""
    if raw[:4] in ZIP_MAGIC:
        return "xlsx"
    if raw[:8] == OLE2_MAGIC:
        return "xls"
    return "csv"


def unrecognised(kind):
    return BadRequest(
        "Unrecognized format: the content is not a readable %s file." % kind
    )


def spreadsheet_cell(value):
    """Normalise one workbook cell to a JSON value (see AMBIGUITIES T48)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        # `.xls` reports every number as a float; narrow whole numbers so the
        # same table ingests identically from CSV, `.xls` and `.xlsx`.
        return int(value) if value.is_integer() else value
    if isinstance(value, datetime.datetime):
        if value.time() == datetime.time(0, 0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def header_text(value):
    """Column names are always strings (see AMBIGUITIES T52)."""
    if value == "" or value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(spreadsheet_cell(value)).strip()


def _blank_row(row):
    return all(cell == "" for cell in row)


def build_grid(grid):
    """Turn a rectangular-ish sheet into (columns, rows) (see AMBIGUITIES T49)."""
    rows = [list(row) for row in grid]
    width = max((len(row) for row in rows), default=0)
    rows = [row + [""] * (width - len(row)) for row in rows]
    # Trim the trailing empty columns that spreadsheet apps leave behind.
    while width and all(row[width - 1] == "" for row in rows):
        width -= 1
    rows = [row[:width] for row in rows]
    rows = [row for row in rows if not _blank_row(row)]
    if len(rows) < 2:
        raise BadRequest(NON_TABULAR_MESSAGE)
    columns = [header_text(cell) for cell in rows[0]]
    body = []
    for row in rows[1:]:
        cells = row[:len(columns)]
        cells.extend([""] * (len(columns) - len(cells)))
        body.append(cells)
    return columns, body


def read_xlsx(raw):
    """Read the first worksheet of an .xlsx workbook."""
    try:
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            raise unrecognised(".xlsx")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
        if not any(name.startswith("xl/") for name in names):
            raise unrecognised(".xlsx")
    except (zipfile.BadZipFile, OSError, ValueError):
        raise unrecognised(".xlsx")
    try:
        book = openpyxl.load_workbook(
            io.BytesIO(raw), data_only=True, read_only=True
        )
    except Exception:
        raise unrecognised(".xlsx")
    try:
        sheets = book.worksheets
        if not sheets:
            raise BadRequest(NON_TABULAR_MESSAGE)
        grid = [
            [spreadsheet_cell(cell) for cell in row]
            for row in sheets[0].iter_rows(values_only=True)
        ]
    finally:
        book.close()
    return build_grid(grid)


def read_xls(raw):
    """Read the first worksheet of a legacy .xls workbook."""
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception:
        raise unrecognised(".xls")
    if not book.nsheets:
        raise BadRequest(NON_TABULAR_MESSAGE)
    sheet = book.sheet_by_index(0)
    grid = []
    for index in range(sheet.nrows):
        grid.append(
            [xls_cell(cell, book.datemode) for cell in sheet.row(index)]
        )
    return build_grid(grid)


def xls_cell(cell, datemode):
    """Map one xlrd cell (type + value) onto a JSON value."""
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return spreadsheet_cell(xlrd.xldate_as_datetime(cell.value, datemode))
        except Exception:
            return spreadsheet_cell(cell.value)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return ""
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    return spreadsheet_cell(cell.value)


# --------------------------------------------------------------- ingestion ---

def build_table(raw, charset=None):
    """Ingest raw bytes of any accepted format into (columns, rows).

    `charset` applies - and is validated - only on the text CSV branch (T47).
    """
    kind = detect_format(raw)
    if kind == "xlsx":
        return read_xlsx(raw)
    if kind == "xls":
        return read_xls(raw)
    codec = resolve_charset(charset)
    text = decode(raw, codec)
    if _looks_non_tabular(raw, text):
        raise BadRequest("Unrecognized format: the content is not a CSV table.")
    return parse_table(text)


def convert_source(source, charset=None, max_size=None):
    """Full ingestion pipeline for one source URL."""
    url = validate_url(source)
    charset_error = None
    try:
        resolve_charset(charset)
    except BadRequest as exc:
        # Held back: a spreadsheet source ignores `charset` entirely, so the
        # error only fires once the bytes prove to be text CSV (T47).
        charset_error = exc
    try:
        raw = fetch(url, max_size)
    except NotFound:
        if charset_error is not None:
            raise charset_error
        raise
    columns, rows = build_table(raw, charset)
    return url, columns, rows


def upload_id(raw):
    """Content-addressed id: the same bytes always yield the same id (T43)."""
    return hashlib.sha256(raw).hexdigest()[:16]


# ------------------------------------------------------------------- app ----

def create_app(cache_enabled=None, settings=None):
    """Build the app from the resolved settings, read once here - never per request.

    Configuration is established before anything is served: bad values and unreadable
    files raise `StartupError`, and `STORAGE_DIR` is created now (T57, T65, T76).
    """
    if settings is None:
        settings = resolve_settings()
    settings = dict(settings)
    if cache_enabled is not None:
        settings["cache_enabled"] = bool(cache_enabled)
    settings["storage_dir"] = ensure_storage_dir(settings.get("storage_dir"))

    max_source_size = settings["max_source_size"]
    allowlist = settings["origin_allowlist"]
    require_tls = settings["require_tls"]

    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config[CACHE_CONFIG_KEY] = bool(settings["cache_enabled"])
    app.config[SETTINGS_CONFIG_KEY] = settings
    # The dataset store *is* the cache: a hit is an id already ingested into this
    # directory - by this process or by an earlier one over the same STORAGE_DIR.
    datasets = DatasetStore(settings["storage_dir"])
    app.extensions["datagate_datasets"] = datasets

    def endpoint_url(identifier):
        """The `endpoint` a reply advertises: relative, or absolute https (T74)."""
        path = "/datasets/%s" % identifier
        if require_tls:
            return "https://%s%s" % (request.host, path)
        return path

    def error(message, status):
        response = jsonify({"ok": False, "error": message})
        response.status_code = status
        return response

    @app.before_request
    def enforce_origin_allowlist():
        """Gate every request before routing, when an allowlist is configured."""
        if not allowlist:
            return None
        referer = request.headers.get("Referer")
        if referer is None or not referer.strip():
            raise DataGateError(
                "Forbidden: this service requires a Referer header.", 403
            )
        host = referer_hostname(referer)
        if host is None or not host_allowed(host, allowlist):
            raise DataGateError(
                "Forbidden: the Referer is not in ORIGIN_ALLOWLIST.", 403
            )
        return None

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Access-Control-Expose-Headers"] = "Content-Type"
        return response

    @app.errorhandler(DataGateError)
    def handle_datagate_error(exc):
        return error(exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        message = exc.description or exc.name
        if exc.code == 404:
            message = "Not found: no such route or dataset."
        elif exc.code == 405:
            message = "Method not allowed: this method is not supported here."
        return error(message, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net, still JSON
        app.logger.exception("unexpected error")
        return error("Internal server error.", 500)

    @app.route("/convert", methods=["GET", "OPTIONS"])
    def convert():
        if request.method == "OPTIONS":
            return ("", 204)
        force = parse_force(request.args)
        source = request.args.get("source")
        charset = request.args.get("charset")
        url = validate_url(source)
        identifier = dataset_id(url)

        # Cache hit: the same URL was already ingested by this process, caching is
        # on and this request did not ask for a refresh.  Nothing is re-downloaded
        # and `charset` has nothing to apply to (T59); the reply is byte-identical
        # to the fresh one because it is built by the very same line below.
        if app.config.get(CACHE_CONFIG_KEY, DEFAULT_CACHE_ENABLED) and not force:
            cached = datasets.get(identifier)
            if cached is not None and cached.get("source") == url:
                return jsonify({"ok": True, "endpoint": endpoint_url(identifier)})

        # Ingestion failures propagate with their usual status and envelope, and -
        # because the store is only written on success - leave any previously
        # stored dataset for this id in place and queryable.
        url, columns, rows = convert_source(url, charset, max_source_size)
        datasets[identifier] = {"source": url, "columns": columns, "rows": rows}
        return jsonify({"ok": True, "endpoint": endpoint_url(identifier)})

    def select(identifier, started):
        """Shared query pipeline: filter -> sort -> paginate one dataset."""
        dataset = datasets.get(identifier)
        if dataset is None:
            raise NotFound("Unknown dataset id: %r" % identifier)
        columns = list(dataset["columns"])
        controls = parse_controls(request.args, columns)
        filters = parse_filters(request.args, columns)

        budget = app.config.get("DATAGATE_QUERY_TIMEOUT", DEFAULT_QUERY_TIMEOUT)
        deadline = None if budget is None else started + float(budget)

        def check_deadline():
            if deadline is not None and time.perf_counter() > deadline:
                raise BadRequest(
                    "Query timed out: the query exceeded its time budget."
                )

        # rowid is the 1-based source-file row number with the header as row 1,
        # so the first data row is 2.  It travels with its row through sorting.
        records = []
        for position, row in enumerate(dataset["rows"]):
            if not position % DEADLINE_CHECK_EVERY:
                check_deadline()
            if not filters or matches(row, filters):
                records.append((position + 2, row))
        check_deadline()

        # `total` is the filtered count, taken before pagination.
        total = len(records)
        if controls["sort_index"] is not None:
            index = controls["sort_index"]
            records = sorted(
                records,
                key=lambda record: sort_key(record[1][index]),
                reverse=controls["sort_desc"],
            )
        check_deadline()
        offset = controls["offset"]
        page = records[offset:offset + controls["size"]]
        return columns, controls, page, total

    @app.route("/datasets/<identifier>", methods=["GET", "OPTIONS"])
    def get_dataset(identifier):
        if request.method == "OPTIONS":
            return ("", 204)
        started = time.perf_counter()
        columns, controls, page, total = select(identifier, started)

        if controls["shape"] == "objects":
            rows = []
            for rowid, row in page:
                item = dict(zip(columns, row))
                if controls["show_rowid"]:
                    item["rowid"] = rowid
                rows.append(item)
        else:
            rows = [list(row) for _, row in page]

        query_ms = max(0.0, round((time.perf_counter() - started) * 1000.0, 3))
        payload = {"ok": True, "columns": columns, "rows": rows}
        if controls["show_total"]:
            payload["total"] = total
        payload["query_ms"] = query_ms
        return jsonify(payload)

    @app.route("/datasets/<identifier>/export", methods=["GET", "OPTIONS"])
    def export_dataset(identifier):
        """CSV download of the same page `/datasets/<id>` would serve.

        `_shape`, `_rowid` and `_total` are still validated but cannot change
        the bytes (see AMBIGUITIES T40).
        """
        if request.method == "OPTIONS":
            return ("", 204)
        started = time.perf_counter()
        columns, _controls, page, _total = select(identifier, started)

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(columns)
        for _rowid, row in page:
            writer.writerow([csv_cell(value) for value in row])

        response = app.response_class(buffer.getvalue().encode("utf-8"))
        response.headers["Content-Type"] = "text/csv"
        response.headers["Content-Disposition"] = (
            'attachment; filename="%s.csv"' % identifier
        )
        return response

    @app.route("/upload", methods=["POST", "OPTIONS"])
    def upload():
        if request.method == "OPTIONS":
            return ("", 204)
        if (request.mimetype or "").lower() != MULTIPART_TYPE:
            raise DataGateError(
                "Unsupported media type: /upload requires a %s body." % MULTIPART_TYPE,
                415,
            )
        raw = read_upload(request)
        check_source_size(len(raw), max_source_size)
        identifier = upload_id(raw)
        columns, rows = build_table(raw, request.args.get("charset"))
        datasets[identifier] = {
            "source": "upload:%s" % identifier,
            "columns": columns,
            "rows": rows,
        }
        return jsonify({"ok": True, "endpoint": endpoint_url(identifier)})

    return app


def csv_cell(value):
    """Render one stored value as CSV text (see AMBIGUITIES T53)."""
    if value == "" or value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def read_upload(req):
    """Pull the uploaded bytes out of a multipart request (T44, T45, T46)."""
    try:
        files = req.files
        form = req.form
    except HTTPException as exc:
        if exc.code and exc.code >= 500:
            raise
        raise BadRequest("Malformed multipart body: the form could not be parsed.")
    except (ValueError, TypeError):
        raise BadRequest("Malformed multipart body: the form could not be parsed.")
    for name in UPLOAD_FIELDS:
        if name in files:
            return files[name].read()
    for name in UPLOAD_FIELDS:
        if name in form:
            return form[name].encode("utf-8")
    raise BadRequest(
        "Missing file field: the form must carry a 'file' or 'attachment' part."
    )


# --------------------------------------------------------------- filtering ---

def parse_filters(args, columns):
    """Validate every `<column>__<comparator>=<value>` param on the request.

    Returns a list of `(column_index, comparator, value)` in request order, with
    the value already float-parsed for the numeric comparators.
    """
    filters = []
    # `args.items(multi=True)` preserves request order; dedupe so a repeated key
    # is inspected once (and reported once).
    for key in dict.fromkeys(key for key, _ in args.items(multi=True)):
        if key.startswith("_"):
            continue  # a control-shaped name is never a filter (T32)
        if FILTER_SEPARATOR not in key:
            continue  # not filter-shaped: ignored, not an error
        values = args.getlist(key)
        if len(values) > 1:
            raise BadRequest(
                "Duplicate filter key %r: supply each filter at most once." % key
            )
        # The comparator is the final segment; the column may itself contain
        # `__`, so the split is from the right (T29).
        column, comparator = key.rsplit(FILTER_SEPARATOR, 1)
        if comparator not in COMPARATORS:
            raise BadRequest(
                "Invalid comparator %r: expected one of 'exact', 'contains', "
                "'less', 'greater'." % comparator
            )
        if column not in columns:
            raise BadRequest("Unknown filter column %r." % column)
        value = values[0]
        if comparator in NUMERIC_COMPARATORS:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise BadRequest(
                    "Invalid filter %r: %r is not numeric." % (key, values[0])
                )
        filters.append((columns.index(column), comparator, value))
    return filters


def cell_text(value):
    """The string a cell is compared as by `exact`/`contains` (see T30)."""
    return value if isinstance(value, str) else str(value)


def cell_number(value):
    """The float a cell compares as, or None when it is not a numeric value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def matches(row, filters):
    """True when a row satisfies every filter (filters are ANDed)."""
    for index, comparator, value in filters:
        cell = row[index]
        if comparator == "exact":
            if cell_text(cell) != value:
                return False
        elif comparator == "contains":
            if value not in cell_text(cell):
                return False
        else:
            number = cell_number(cell)
            if number is None:
                return False  # non-numeric stored values never match
            if comparator == "less":
                if not number < value:
                    return False
            elif not number > value:
                return False
    return True


# ---------------------------------------------------------- query controls ---

def parse_control_int(raw, name, minimum, default, wording):
    """Parse `_size`/`_offset`; anything but a plain integer literal is a 400."""
    if raw is None:
        return default
    text = raw.strip()
    if not _CONTROL_INT_RE.match(text) or int(text) < minimum:
        raise BadRequest("Invalid %r: must be %s." % (name, wording))
    return int(text)


def parse_toggle(raw, name):
    """A visibility toggle is valid only with the value `hide`; True == visible."""
    if raw is None:
        return True
    if raw != "hide":
        raise BadRequest("Invalid %r: the only supported value is 'hide'." % name)
    return False


def resolve_sort_column(raw, name, columns):
    """Validate one sort parameter, returning the index of the column it names."""
    if raw is None:
        return None
    if raw == "":
        raise BadRequest("Invalid %r: a column name is required." % name)
    if raw not in columns:
        raise BadRequest("Invalid %r: unknown column %r." % (name, raw))
    return columns.index(raw)


def sort_key(value):
    """A total ordering across the mixed types a column may hold (see T23).

    Numbers sort before text, each within its own kind - CSV columns are not
    guaranteed to be homogeneous and `int < str` raises in Python.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value, "")
    return (1, 0.0, str(value))


def parse_controls(args, columns):
    """Validate every control parameter for `GET /datasets/<id>`."""
    for name in CONTROL_PARAMS:
        if len(args.getlist(name)) > 1:
            raise BadRequest("Repeated control parameter %r: supply it at most once." % name)

    size = parse_control_int(
        args.get("_size"), "_size", 1, DEFAULT_SIZE, "a positive integer"
    )
    offset = parse_control_int(
        args.get("_offset"), "_offset", 0, DEFAULT_OFFSET, "a non-negative integer"
    )

    shape = args.get("_shape")
    if shape is None:
        shape = DEFAULT_SHAPE
    elif shape not in SHAPES:
        raise BadRequest("Invalid '_shape': must be 'lists' or 'objects'.")

    show_rowid = parse_toggle(args.get("_rowid"), "_rowid")
    show_total = parse_toggle(args.get("_total"), "_total")

    # Both sort parameters are validated when both are present; `_sort_desc`
    # then decides the order (see AMBIGUITIES T25).
    ascending = resolve_sort_column(args.get("_sort"), "_sort", columns)
    descending = resolve_sort_column(args.get("_sort_desc"), "_sort_desc", columns)
    if descending is not None:
        sort_index, sort_desc = descending, True
    else:
        sort_index, sort_desc = ascending, False

    return {
        "size": size,
        "offset": offset,
        "shape": shape,
        "show_rowid": show_rowid,
        "show_total": show_total,
        "sort_index": sort_index,
        "sort_desc": sort_desc,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="datagate.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="start the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    args = parser.parse_args(argv)
    if args.command == "start":
        # Configuration is resolved before the port is bound, so invalid config or an
        # unreadable config file exits non-zero without ever serving a request.
        try:
            app = create_app()
        except StartupError as exc:
            sys.exit("datagate: %s" % exc)
        app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

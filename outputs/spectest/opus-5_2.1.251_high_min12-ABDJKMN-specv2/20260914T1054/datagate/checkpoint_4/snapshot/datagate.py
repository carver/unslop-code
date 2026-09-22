"""datagate - convert remote CSV/spreadsheet files into queryable JSON datasets.

Start with:

    python datagate.py start --port <port> --address <address>
"""
import argparse
import codecs
import csv
import datetime
import hashlib
import io
import json
import math
import re
import sys
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
MAX_BYTES = 64 * 1024 * 1024

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


def fetch(source):
    """GET the source; any transport failure or remote HTTP error is a 404."""
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
    if len(content) > MAX_BYTES:
        raise BadRequest("Source is too large to convert.")
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
        return int(text)
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


def convert_source(source, charset=None):
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
        raw = fetch(url)
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

def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    datasets = {}
    app.extensions["datagate_datasets"] = datasets

    def error(message, status):
        response = jsonify({"ok": False, "error": message})
        response.status_code = status
        return response

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
        source = request.args.get("source")
        charset = request.args.get("charset")
        url, columns, rows = convert_source(source, charset)
        identifier = dataset_id(url)
        datasets[identifier] = {"source": url, "columns": columns, "rows": rows}
        return jsonify({"ok": True, "endpoint": "/datasets/%s" % identifier})

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
        identifier = upload_id(raw)
        columns, rows = build_table(raw, request.args.get("charset"))
        datasets[identifier] = {
            "source": "upload:%s" % identifier,
            "columns": columns,
            "rows": rows,
        }
        return jsonify({"ok": True, "endpoint": "/datasets/%s" % identifier})

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


app = create_app()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="datagate.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="start the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    args = parser.parse_args(argv)
    if args.command == "start":
        app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

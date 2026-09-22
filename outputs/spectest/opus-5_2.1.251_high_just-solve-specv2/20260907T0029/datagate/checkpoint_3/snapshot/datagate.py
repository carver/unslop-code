"""datagate - convert remote CSV files into queryable JSON datasets.

Usage:
    python datagate.py start --port <port> --address <address>
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import json
import re
import sys
import threading
import time
from urllib.parse import urlsplit

import requests
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
# Dataset store
# --------------------------------------------------------------------------

_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()


def dataset_id(source: str) -> str:
    """Deterministic id derived only from the source URL string."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


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


def looks_binary(data: bytes) -> bool:
    if not data:
        return True
    sample = data[:4096]
    if sample.startswith((b"%PDF", b"PK\x03\x04", b"\x89PNG", b"GIF8", b"\xff\xd8\xff",
                          b"\x1f\x8b", b"BZh", b"\x7fELF", b"SQLite format 3")):
        return True
    return False


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


def parse_table(text: str):
    """Parse decoded text into (columns, rows, rowids, texts); 400 when non-tabular.

    ``rowids`` are 1-based source-file row numbers counted from the header row,
    so the header is 1 and the first data row is 2.  ``texts`` mirrors ``rows``
    with the untouched source text of every cell, which column filters compare
    against alongside the coerced value.
    """
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

    header = rows[0]
    columns = [cell.strip() for cell in header]
    if not columns or all(col == "" for col in columns):
        raise DataGateError(400, "Non-tabular content: missing header row")

    width = len(columns)
    data_rows = []
    data_texts = []
    rowids = []
    for number, raw in enumerate(rows[1:], start=2):
        values = list(raw[:width])
        if len(values) < width:
            values.extend([""] * (width - len(values)))
        data_rows.append([coerce(cell) for cell in values])
        data_texts.append(values)
        rowids.append(number)

    if not data_rows:
        raise DataGateError(
            400,
            "Non-tabular content: a header row and at least one data row are required",
        )

    return columns, data_rows, rowids, data_texts


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


@app.route("/convert", methods=["GET", "HEAD", "OPTIONS"])
def convert():
    if request.method == "OPTIONS":
        return ("", 204)

    if "source" not in request.args:
        raise DataGateError(400, "Missing required query parameter: source")

    raw_source = request.args.get("source")
    source = validate_source(raw_source)
    charset = validate_charset(request.args.get("charset")) \
        if "charset" in request.args else None

    body = fetch(source)
    if looks_binary(body):
        raise DataGateError(400, "Non-tabular content: source is not text")

    text = decode_body(body, charset)
    columns, rows, rowids, texts = parse_table(text)

    ds_id = dataset_id(raw_source)
    store_dataset(ds_id, columns, rows, rowids, texts)

    return jsonify({"ok": True, "endpoint": "/datasets/%s" % ds_id})


@app.route("/datasets/<dataset>", methods=["GET", "HEAD", "OPTIONS"])
def dataset_query(dataset: str):
    if request.method == "OPTIONS":
        return ("", 204)

    started = time.perf_counter()
    record = get_dataset(dataset)
    if record is None:
        raise DataGateError(404, "Unknown dataset id: %r" % dataset)

    args = request.args
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


@app.route("/", methods=["GET", "HEAD", "OPTIONS"])
def index():
    if request.method == "OPTIONS":
        return ("", 204)
    return jsonify(
        {
            "ok": True,
            "service": "datagate",
            "endpoints": ["/convert?source=<url>[&charset=<enc>]", "/datasets/<id>"],
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
    app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""datagate -- ingest remote CSV files and serve them as queryable JSON datasets.

    python datagate.py start --port <port> --address <address>
"""

import argparse
import codecs
import csv
import hashlib
import io
import json
import math
import re
import sys
import threading
import time
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"

# "rows returns at most 100 items (or all rows if fewer)" / "Default row limit is 100".
ROW_LIMIT = 100

# Delimiters considered when inferring the dialect. The spec requires ",", ";"
# and "\t" as a minimum; "|" is a superset that costs nothing because candidates
# that do not split the header into >= 2 fields are discarded.
CANDIDATE_DELIMITERS = (",", ";", "\t", "|")

FETCH_TIMEOUT = 20.0

# Budget for the filter/sort/paginate pipeline of `/datasets/<id>`; exceeding
# it is "query timeout" -> HTTP 400. Read from the module namespace at call
# time so it can be lowered in tests. See AMBIGUITIES T32.
QUERY_TIMEOUT = 5.0
MAX_BYTES = 64 * 1024 * 1024
SNIFF_CHARS = 65536

# Type inference. ASCII-only grammars: `\d` would also match Unicode digits,
# which is exactly the locale dependence the determinism section forbids.
_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_DECIMAL_RE = re.compile(
    r"^[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)
_TIME_RE = re.compile(r"^[0-9]{1,2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?\s*(?:[APap]\.?[Mm]\.?)?$")

# Content types that can never be a delimited table.
_NON_TABULAR_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "application/json",
    "application/ld+json",
    "application/xml",
    "text/xml",
    "application/pdf",
    "application/zip",
    "application/gzip",
}
_NON_TABULAR_PREFIXES = ("image/", "audio/", "video/", "font/")

app = Flask(__name__)

_store = {}
_store_lock = threading.Lock()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class DataGateError(Exception):
    """An error that maps onto one of the spec's documented status codes."""

    status = 400

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class BadRequest(DataGateError):
    status = 400


class NotFound(DataGateError):
    status = 404


def error_response(message, status):
    response = jsonify({"ok": False, "error": message})
    response.status_code = status
    return response


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


def reset_store():
    """Drop every ingested dataset (used by the tests)."""
    with _store_lock:
        _store.clear()


def dataset_id(source):
    """Same `source` URL string always maps to the same dataset id."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------


def validate_url(source):
    """Reject anything that is not a fetchable absolute http(s) URL."""
    try:
        parts = urlsplit(source.strip())
    except ValueError:
        raise BadRequest("Invalid URL: {!r}".format(source))
    if parts.scheme.lower() not in ("http", "https"):
        raise BadRequest(
            "Invalid URL: expected an http(s) URL, got {!r}".format(source)
        )
    if not parts.hostname:
        raise BadRequest("Invalid URL: missing host in {!r}".format(source))
    try:
        parts.port  # raises ValueError for a malformed port
    except ValueError:
        raise BadRequest("Invalid URL: bad port in {!r}".format(source))
    return source


def resolve_charset(charset):
    """Validate a caller-supplied charset. Empty/absent means "detect"."""
    if charset is None or not charset.strip():
        return None
    name = charset.strip()
    try:
        codecs.lookup(name)
    except (LookupError, ValueError, TypeError):
        raise BadRequest("Unsupported or malformed charset: {!r}".format(charset))
    return name


# --------------------------------------------------------------------------
# Fetching and decoding
# --------------------------------------------------------------------------


def fetch(source):
    """Return (bytes, content_type). Any transport or remote HTTP error is 404."""
    try:
        response = requests.get(
            source,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
        )
    except requests.RequestException as exc:
        raise NotFound("Source unreachable: {}".format(exc))
    if response.status_code >= 400:
        raise NotFound(
            "Remote HTTP error {} for {}".format(response.status_code, source)
        )
    content = response.content
    if len(content) > MAX_BYTES:
        raise BadRequest("Source is too large to ingest")
    content_type = response.headers.get("Content-Type", "")
    return content, content_type


_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode(content, charset):
    """Decode with the declared charset, else detect one. Returns (text, encoding)."""
    if charset is not None:
        try:
            text = content.decode(charset)
        except (UnicodeDecodeError, LookupError, ValueError) as exc:
            raise BadRequest(
                "Unsupported or malformed charset {!r}: {}".format(charset, exc)
            )
        return _strip_bom(text), charset
    text, encoding = _detect_decode(content)
    return _strip_bom(text), encoding


def _strip_bom(text):
    return text[1:] if text.startswith("\ufeff") else text


def _detect_decode(content):
    for bom, encoding in _BOMS:
        if content.startswith(bom):
            try:
                return content.decode(encoding), encoding
            except UnicodeDecodeError:
                break
    try:
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(content).best()
        if best is not None:
            return str(best), (best.encoding or "utf-8")
    except Exception:  # detection is best-effort; the fallback below never fails
        pass
    return content.decode("cp1252", errors="replace"), "cp1252"


def _is_wide_encoding(encoding):
    name = (encoding or "").lower().replace("_", "-")
    return name.startswith("utf-16") or name.startswith("utf-32")


# --------------------------------------------------------------------------
# CSV parsing
# --------------------------------------------------------------------------


def _read_rows(text, delimiter):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = []
    for row in reader:
        if any(cell.strip() for cell in row):
            rows.append(row)
    return rows


def sniff_delimiter(text):
    """Infer the delimiter from the input. Returns None when none applies."""
    sample = text[:SNIFF_CHARS]
    best_score = None
    best_delimiter = None
    for delimiter in CANDIDATE_DELIMITERS:
        try:
            rows = _read_rows(sample, delimiter)
        except csv.Error:
            continue
        if not rows:
            continue
        width = len(rows[0])
        if width < 2:
            continue
        # The final sampled row may have been cut mid-line; ignore it when the
        # sample was truncated and there is enough material to judge without it.
        data = rows[1:]
        if len(text) > SNIFF_CHARS and len(data) > 1:
            data = data[:-1]
        consistency = (
            sum(1 for row in data if len(row) == width) / len(data) if data else 1.0
        )
        score = (round(consistency, 6), width)
        if best_score is None or score > best_score:
            best_score = score
            best_delimiter = delimiter
    return best_delimiter


def looks_non_tabular(content, content_type, text, encoding=None):
    """Report why `text` cannot be a delimited table, or None if it might be."""
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type in _NON_TABULAR_TYPES or media_type.startswith(_NON_TABULAR_PREFIXES):
        return "Non-tabular content: unsupported content type {!r}".format(media_type)
    # NUL bytes mean binary -- except under UTF-16/32, where they are structural.
    if not _is_wide_encoding(encoding) and b"\x00" in content[:SNIFF_CHARS]:
        return "Non-tabular content: input appears to be binary"
    if "\x00" in text[:SNIFF_CHARS]:
        return "Non-tabular content: input appears to be binary"
    stripped = text.strip()
    if not stripped:
        return "Non-tabular content: source is empty"
    if stripped[0] == "<":
        return "Non-tabular content: input looks like markup, not CSV"
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
        except ValueError:
            pass
        else:
            return "Non-tabular content: input looks like JSON, not CSV"
    return None


def parse_csv(content, content_type, text, encoding=None):
    """Return (columns, rows) or raise BadRequest for non-tabular input."""
    problem = looks_non_tabular(content, content_type, text, encoding)
    if problem:
        raise BadRequest(problem)

    delimiter = sniff_delimiter(text)
    if delimiter is None:
        raise BadRequest(
            "Non-tabular content: no delimiter could be inferred from the input"
        )
    try:
        rows = _read_rows(text, delimiter)
    except csv.Error as exc:
        raise BadRequest("Non-tabular content: could not parse CSV ({})".format(exc))
    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: a valid file requires at least one header row "
            "and one data row"
        )

    columns = list(rows[0])
    width = len(columns)
    data = []
    for row in rows[1:]:
        # Align each row to the header so rows and columns stay positional.
        if len(row) < width:
            row = list(row) + [""] * (width - len(row))
        elif len(row) > width:
            row = list(row[:width])
        data.append([coerce(cell) for cell in row])
    return columns, data


def coerce(raw):
    """Strings stay text; integers/decimals become JSON numbers; times stay text."""
    if not isinstance(raw, str):
        return raw
    token = raw.strip()
    if not token:
        return raw
    if _TIME_RE.match(token):
        return raw
    if _INT_RE.match(token):
        return int(token)
    if _DECIMAL_RE.match(token):
        value = float(token)
        return value if math.isfinite(value) else raw
    return raw


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.route("/convert", methods=["GET"])
def convert():
    source = request.args.get("source")
    if source is None or not source.strip():
        raise BadRequest("Missing required query parameter: source")

    validate_url(source)
    charset = resolve_charset(request.args.get("charset"))

    content, content_type = fetch(source)
    text, encoding = decode(content, charset)
    columns, rows = parse_csv(content, content_type, text, encoding)

    identifier = dataset_id(source)
    with _store_lock:
        _store[identifier] = {"source": source, "columns": columns, "rows": rows}
    return jsonify({"ok": True, "endpoint": "/datasets/{}".format(identifier)})


@app.route("/datasets/<identifier>", methods=["GET"])
def get_dataset(identifier):
    started = time.perf_counter()
    # The dataset has to be resolved first: `_sort` cannot be validated without
    # the column list, so the lookup precedes every control check.
    with _store_lock:
        entry = _store.get(identifier)
    if entry is None:
        raise NotFound("Unknown dataset id: {}".format(identifier))

    args = request.args
    columns = list(entry["columns"])

    _reject_repeats(args)
    size = _size_param(args)
    offset = _integer_param(args, "_offset", default=0, minimum=0,
                            expected="a non-negative integer")
    shape = _shape_param(args)
    hide_rowid = _hide_toggle(args, "_rowid")
    hide_total = _hide_toggle(args, "_total")
    sort_index, descending = _sort_param(args, columns)
    # Controls are validated before filters; see AMBIGUITIES T33.
    filters = _filter_params(args, columns)

    # (rowid, row) pairs: rowid is the 1-based position in the source file and
    # never changes, so sorting and paging do not renumber it.
    numbered = list(enumerate(entry["rows"], start=1))
    # "Filtering precedes sorting" / "total counts filtered rows before
    # pagination", so the pipeline is filter -> sort -> slice.
    if filters:
        numbered = _apply_filters(numbered, filters, started)
    _check_deadline(started)
    total = len(numbered)
    if sort_index is not None:
        numbered.sort(
            key=lambda pair: _sort_key(pair[1][sort_index]), reverse=descending
        )
        _check_deadline(started)
    page = numbered[offset:offset + size]

    if shape == "objects":
        rows = [_as_object(rowid, row, columns, hide_rowid) for rowid, row in page]
    else:
        rows = [list(row) for _, row in page]

    query_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    payload = {
        "ok": True,
        "columns": columns,
        "rows": rows,
        "query_ms": round(query_ms, 4),
    }
    if not hide_total:
        payload["total"] = total
    return jsonify(payload)


# --------------------------------------------------------------------------
# Control parameters
# --------------------------------------------------------------------------

# Every parameter that `/datasets/<id>` reserves for itself; repeating any of
# them is an error.
CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid",
                  "_total")

SHAPES = ("lists", "objects")

# ASCII-only integer grammar, for the same determinism reasons as `_INT_RE`:
# `int()` would also accept `1_0` and Unicode digits.
_PARAM_INT_RE = re.compile(r"^[+-]?[0-9]+$")


def _reject_repeats(args):
    for name in CONTROL_PARAMS:
        if len(args.getlist(name)) > 1:
            raise BadRequest(
                "Repeated control parameter: {} may be given at most once".format(name)
            )


def _integer_param(args, name, default, minimum, expected):
    raw = args.get(name)
    if raw is None:
        return default
    token = raw.strip()
    if not _PARAM_INT_RE.match(token) or int(token) < minimum:
        raise BadRequest(
            "Invalid {}: expected {}, got {!r}".format(name, expected, raw)
        )
    return int(token)


def _size_param(args):
    if "_size" in args:
        return _integer_param(args, "_size", default=ROW_LIMIT, minimum=1,
                              expected="a positive integer")
    # Legacy spelling from the earlier row-limit section; see AMBIGUITIES T12.
    return _requested_limit(args.get("limit"))


def _shape_param(args):
    raw = args.get("_shape")
    if raw is None:
        return "lists"
    if raw not in SHAPES:
        raise BadRequest(
            "Invalid _shape: expected one of {}, got {!r}".format(
                ", ".join(SHAPES), raw
            )
        )
    return raw


def _hide_toggle(args, name):
    """`_rowid`/`_total` accept exactly one value: `hide`."""
    raw = args.get(name)
    if raw is None:
        return False
    if raw != "hide":
        raise BadRequest(
            "Invalid {} value: expected 'hide', got {!r}".format(name, raw)
        )
    return True


def _sort_param(args, columns):
    """Return (column index or None, descending). `_sort_desc` wins outright."""
    raw = args.get("_sort_desc")
    descending = raw is not None
    if not descending:
        raw = args.get("_sort")
    if raw is None:
        return None, False
    name = "_sort_desc" if descending else "_sort"
    if not raw.strip():
        raise BadRequest("Invalid {}: column name must not be empty".format(name))
    if raw not in columns:
        raise BadRequest("Unknown column for {}: {!r}".format(name, raw))
    return columns.index(raw), descending


def _sort_key(value):
    """Total order over mixed cells: numbers first, then text by code point."""
    if isinstance(value, bool):
        return (1, 0.0, str(value))
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0.0, "" if value is None else str(value))


def _as_object(rowid, row, columns, hide_rowid):
    obj = {} if hide_rowid else {"rowid": rowid}
    for column, value in zip(columns, row):
        obj[column] = value
    return obj


def _requested_limit(raw):
    """Optional `limit`, clamped to the documented maximum of 100 rows."""
    if raw is None or not raw.strip():
        return ROW_LIMIT
    try:
        value = int(raw.strip())
    except ValueError:
        return ROW_LIMIT
    if value < 0:
        return ROW_LIMIT
    return min(value, ROW_LIMIT)


# --------------------------------------------------------------------------
# Column-level filtering
# --------------------------------------------------------------------------

COMPARATORS = ("exact", "contains", "less", "greater")

# How often the filter loop consults the clock. Checking every row would cost
# more than the filtering itself; 0 is included so a zero budget trips at once.
_DEADLINE_STRIDE = 256


def _check_deadline(started):
    budget = QUERY_TIMEOUT
    if budget is not None and (time.perf_counter() - started) > budget:
        raise BadRequest(
            "Query timeout: exceeded the {}s query budget".format(budget)
        )


def _is_filter_key(key):
    """Filter params carry `__` and do not begin with `_` (T28, T34)."""
    return not key.startswith("_") and "__" in key


def _to_float(value):
    """`float` parse of a stored or filter value; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_text(value):
    """Text form of a cell for the string comparators; see AMBIGUITIES T25."""
    return value if isinstance(value, str) else str(value)


def _filter_params(args, columns):
    """Parse `<column>__<comparator>=<value>` into (index, comparator, target)."""
    keys = [key for key in args.keys() if _is_filter_key(key)]
    for key in keys:
        if len(args.getlist(key)) > 1:
            raise BadRequest(
                "Duplicate filter key: {} may be given at most once".format(key)
            )

    filters = []
    for key in keys:
        # Split on the LAST `__` so a column named `a__b` stays addressable.
        column, _, comparator = key.rpartition("__")
        if comparator not in COMPARATORS:
            raise BadRequest(
                "Invalid comparator {!r} in filter {!r}: expected one of {}".format(
                    comparator, key, "|".join(COMPARATORS)
                )
            )
        if column not in columns:
            raise BadRequest("Unknown filter column: {!r}".format(column))
        raw = args.get(key)
        if comparator in ("less", "greater"):
            target = _to_float(raw)
            if target is None:
                raise BadRequest(
                    "Comparator target not numeric: {}={!r} requires a number".format(
                        key, raw
                    )
                )
        else:
            target = raw
        filters.append((columns.index(column), comparator, target))
    return filters


def _matches(row, index, comparator, target):
    value = row[index]
    if comparator == "exact":
        return _as_text(value) == target
    if comparator == "contains":
        return target in _as_text(value)
    number = _to_float(value)
    if number is None:  # non-numeric stored values never match
        return False
    return number < target if comparator == "less" else number > target


def _apply_filters(numbered, filters, started):
    """Keep the (rowid, row) pairs matching every filter -- filters are ANDed."""
    kept = []
    for position, pair in enumerate(numbered):
        if position % _DEADLINE_STRIDE == 0:
            _check_deadline(started)
        row = pair[1]
        if all(_matches(row, *spec) for spec in filters):
            kept.append(pair)
    return kept


# --------------------------------------------------------------------------
# Envelope + CORS
# --------------------------------------------------------------------------


@app.errorhandler(DataGateError)
def handle_datagate_error(exc):
    return error_response(exc.message, exc.status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    message = exc.description or exc.name
    if exc.code == 404:
        message = "Not found: {}".format(request.path)
    return error_response(message, exc.code or 500)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_response("Internal error: {}".format(exc), 500)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    requested = request.headers.get("Access-Control-Request-Headers")
    response.headers["Access-Control-Allow-Headers"] = requested or "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"
    return response


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(prog="datagate.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="run the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "start":
        app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

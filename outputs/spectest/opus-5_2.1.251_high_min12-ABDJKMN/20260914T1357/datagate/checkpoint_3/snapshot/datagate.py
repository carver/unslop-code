#!/usr/bin/env python3
"""datagate — convert remote CSV files into queryable JSON datasets."""
import argparse
import codecs
import csv
import hashlib
import io
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
MAX_BYTES = 64 * 1024 * 1024
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

BINARY_MAGIC = (
    b"\x89PNG", b"GIF8", b"\xff\xd8\xff", b"%PDF", b"PK\x03\x04",
    b"\x1f\x8b", b"\x7fELF", b"BM", b"Rar!", b"\xd0\xcf\x11\xe0",
    b"SQLite format 3", b"\xfd7zXZ", b"OggS", b"RIFF",
)

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
    if len(content) > MAX_BYTES:
        raise bad_request("Source is too large (%d bytes)." % len(content))
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
def reject_binary(raw):
    for magic in BINARY_MAGIC:
        if raw.startswith(magic):
            raise bad_request("Non-tabular content: binary payload.")


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
        raise bad_request(
            "Non-tabular content: a valid file needs a header row and at least "
            "one data row.")
    columns = [cell.strip() for cell in rows[0]]
    width = len(columns)
    data = []
    for row in rows[1:]:
        values = [infer_type(cell) for cell in row[:width]]
        if len(values) < width:
            values.extend([""] * (width - len(values)))
        data.append(values)
    if not data:
        raise bad_request(
            "Non-tabular content: a valid file needs a header row and at least "
            "one data row.")
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
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


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


@app.route("/convert", methods=["GET", "OPTIONS"])
def convert():
    if request.method == "OPTIONS":
        return ("", 204)
    if "source" not in request.args:
        raise bad_request("Query parameter 'source' is required.")
    source = request.args.get("source", "")
    charset = check_charset(request.args.get("charset"))
    url = validate_url(source)

    raw = fetch(url)
    reject_binary(raw)
    text = decode_with(raw, charset) if charset else detect_and_decode(raw)
    columns, rows = parse_table(text)

    ident = dataset_id(source)
    DATASETS[ident] = {"columns": columns, "rows": rows}
    return jsonify({"ok": True, "endpoint": "/datasets/%s" % ident})


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


@app.route("/datasets/<dataset_id_>", methods=["GET", "OPTIONS"])
def dataset(dataset_id_):
    if request.method == "OPTIONS":
        return ("", 204)
    started = time.perf_counter()
    stored = DATASETS.get(dataset_id_)
    if stored is None:
        raise not_found("Unknown dataset id %r." % dataset_id_)

    args = request.args
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

    if shape == "objects":
        rows = []
        for rowid, values in page:
            row = {} if hide_rowid else {"rowid": rowid}
            row.update(zip(columns, values))
            rows.append(row)
    else:
        rows = [values for _, values in page]

    payload = {"ok": True, "columns": columns, "rows": rows}
    if not hide_total:
        payload["total"] = total
    query_ms = round((time.perf_counter() - started) * 1000.0, 3)
    payload["query_ms"] = max(query_ms, 0.0)
    return jsonify(payload)


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
    app.run(host=args.address, port=args.port, threaded=True,
            debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

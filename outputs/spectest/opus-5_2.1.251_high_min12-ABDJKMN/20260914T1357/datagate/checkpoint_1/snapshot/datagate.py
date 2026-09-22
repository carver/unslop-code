#!/usr/bin/env python3
"""datagate — convert remote CSV files into queryable JSON datasets."""
import argparse
import codecs
import csv
import hashlib
import io
import math
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


@app.route("/datasets/<dataset_id_>", methods=["GET", "OPTIONS"])
def dataset(dataset_id_):
    if request.method == "OPTIONS":
        return ("", 204)
    started = time.perf_counter()
    stored = DATASETS.get(dataset_id_)
    if stored is None:
        raise not_found("Unknown dataset id %r." % dataset_id_)
    limit = DEFAULT_ROW_LIMIT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            requested = int(raw_limit)
            if requested > 0:
                limit = requested
        except (TypeError, ValueError):
            pass
    rows = stored["rows"][:limit]
    query_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return jsonify({
        "ok": True,
        "columns": stored["columns"],
        "rows": rows,
        "query_ms": max(query_ms, 0.0),
    })


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

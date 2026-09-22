"""datagate - convert remote CSV files into queryable JSON datasets.

Start with:

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
import time
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_ROW_LIMIT = 100
FETCH_TIMEOUT = 20
MAX_BYTES = 64 * 1024 * 1024

CANDIDATE_DELIMITERS = (",", ";", "\t")

# Numeric literals: plain integers and plain decimals (optionally in exponent form).
# Deliberately excludes nan/inf (not valid JSON), underscores and hex (Python quirks),
# thousands separators and currency/percent signs.  See AMBIGUITIES.md T3.
_INT_RE = re.compile(r"^[+-]?\d+$")
_DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")

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


def convert_source(source, charset=None):
    """Full ingestion pipeline for one source URL."""
    url = validate_url(source)
    codec = resolve_charset(charset)
    raw = fetch(url)
    text = decode(raw, codec)
    if _looks_non_tabular(raw, text):
        raise BadRequest("Non-tabular content: the source is not a CSV table.")
    columns, rows = parse_table(text)
    return url, columns, rows


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
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
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
            message = "Method not allowed: this endpoint only supports GET."
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

    @app.route("/datasets/<identifier>", methods=["GET", "OPTIONS"])
    def get_dataset(identifier):
        if request.method == "OPTIONS":
            return ("", 204)
        started = time.perf_counter()
        limit = parse_limit(request.args.get("limit"))
        dataset = datasets.get(identifier)
        if dataset is None:
            raise NotFound("Unknown dataset id: %r" % identifier)
        columns = list(dataset["columns"])
        rows = [list(row) for row in dataset["rows"][:limit]]
        query_ms = max(0.0, round((time.perf_counter() - started) * 1000.0, 3))
        return jsonify(
            {"ok": True, "columns": columns, "rows": rows, "query_ms": query_ms}
        )

    return app


def parse_limit(raw):
    """Row limit for a dataset query; defaults to 100 (see AMBIGUITIES.md T6)."""
    if raw is None or raw == "":
        return DEFAULT_ROW_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadRequest("Invalid 'limit': must be a positive integer.")
    if value < 1:
        raise BadRequest("Invalid 'limit': must be a positive integer.")
    return value


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

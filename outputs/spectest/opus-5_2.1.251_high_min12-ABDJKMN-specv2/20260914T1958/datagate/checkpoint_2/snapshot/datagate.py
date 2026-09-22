#!/usr/bin/env python3
"""datagate -- turn remote CSV files into deterministic, queryable JSON datasets.

Usage:
    python datagate.py start --port <port> --address <address>
"""
from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import re
import sys
import threading
import time
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"

ROW_LIMIT = 100                 # spec: default row limit
DELIMITERS = (",", ";", "\t")   # spec: minimum supported delimiters
FETCH_TIMEOUT = 30              # seconds
MAX_BYTES = 64 * 1024 * 1024    # refuse absurdly large downloads
MAX_PROSE_TOKENS = 4            # single-column guard, see AMBIGUITIES T9

# Query controls on /datasets/<id>; repeating any of them is a 400.
CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")
SHAPES = ("lists", "objects")

# Strict decimal forms only -- no exponents, no nan/inf, no locale separators.
INT_RE = re.compile(r"^[+-]?[0-9]+$")
DEC_RE = re.compile(r"^[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)$")
# Control parameters are strict: plain digits only, no sign, space, or exponent.
UINT_RE = re.compile(r"^[0-9]+$")

app = Flask(__name__)

_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class DataGateError(Exception):
    """An error that maps onto a documented status code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def error(status: int, message: str):
    response = jsonify({"ok": False, "error": message})
    response.status_code = status
    return response


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def dataset_id(source: str) -> str:
    """Same source URL string -> same id, in this process and any other."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def validate_url(source: str) -> str:
    try:
        parts = urlparse(source)
    except ValueError:
        raise DataGateError(400, f"invalid URL: {source!r}")
    if parts.scheme.lower() not in ("http", "https"):
        raise DataGateError(
            400, "invalid URL: source must be an absolute http:// or https:// URL"
        )
    if not parts.netloc or not parts.hostname:
        raise DataGateError(400, "invalid URL: missing host")
    if any(ch.isspace() for ch in source.strip()):
        raise DataGateError(400, "invalid URL: contains whitespace")
    return source


def validate_charset(name: str) -> str:
    """Reject codec names that do not exist or are not text decoders."""
    try:
        codecs.lookup(name)
        b"".decode(name)
    except (LookupError, TypeError, UnicodeDecodeError, ValueError):
        raise DataGateError(400, f"unsupported or malformed charset: {name!r}")
    return name


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch(url: str) -> bytes:
    try:
        response = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            stream=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
        )
    except requests.RequestException as exc:
        raise DataGateError(404, f"source unreachable: {exc.__class__.__name__}")

    with response:
        if response.status_code >= 400:
            raise DataGateError(
                404, f"remote HTTP error {response.status_code} for {url}"
            )
        chunks, total = [], 0
        try:
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_BYTES:
                    raise DataGateError(400, "source is too large to convert")
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise DataGateError(404, f"source unreachable: {exc.__class__.__name__}")
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode(data: bytes, charset: str | None) -> str:
    """Decode with the caller's charset, else detect, else latin-1."""
    if charset:
        try:
            return data.decode(charset)
        except (LookupError, TypeError, ValueError) as exc:
            raise DataGateError(
                400, f"unsupported or malformed charset {charset!r}: {exc}"
            )

    for bom, encoding in BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, ValueError):
                break

    try:
        return data.decode("utf-8")  # self-identifying, therefore unambiguous
    except UnicodeDecodeError:
        return data.decode("latin-1")  # ambiguous bytes: the never-failing default


# ---------------------------------------------------------------------------
# Tabular parsing
# ---------------------------------------------------------------------------
def _read_rows(text: str, delimiter: str) -> list[tuple[int, list[str]]]:
    """Return (source line number, cells) for every non-blank record."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = []
    start = 1
    for raw in reader:
        cells = [cell.strip() for cell in raw]
        if any(cells):
            rows.append((start, cells))
        start = reader.line_num + 1
    return rows


def _score(rows: list[tuple[int, list[str]]]) -> tuple[float, int] | None:
    """How well does this delimiter explain the file? Higher is better."""
    if len(rows) < 2:
        return None
    width = len(rows[0][1])
    if width < 2:
        return None
    consistent = sum(1 for _, cells in rows if len(cells) == width) / len(rows)
    return (consistent, width)


def looks_non_tabular(text: str) -> str | None:
    """Return a reason if the payload is clearly not a delimited table."""
    if "\x00" in text:
        return "content is binary, not tabular"
    stripped = text.strip()
    if not stripped:
        return "source is empty"
    first = stripped[0]
    if first == "<":
        return "content looks like markup (HTML/XML), not tabular"
    if first in "{[":
        return "content looks like JSON, not tabular"
    return None


def parse_table(text: str) -> tuple[list[str], list[list[str]], list[int]]:
    text = text.lstrip("\ufeff")
    reason = looks_non_tabular(text)
    if reason:
        raise DataGateError(400, reason)

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise DataGateError(
            400, "non-tabular content: need at least one header row and one data row"
        )

    best = None
    for delimiter in DELIMITERS:
        rows = _read_rows(text, delimiter)
        score = _score(rows)
        if score is not None and (best is None or score > best[0]):
            best = (score, rows)

    if best is None:
        # No delimiter present: a single-column table, unless it reads as prose.
        if any(len(line.split()) > MAX_PROSE_TOKENS for line in lines):
            raise DataGateError(400, "non-tabular content: no delimiter found")
        rows = _read_rows(text, "\x01")
        if len(rows) < 2:
            raise DataGateError(
                400,
                "non-tabular content: need at least one header row and one data row",
            )
    else:
        rows = best[1]

    header = rows[0][1]
    width = len(header)
    body, rowids = [], []
    for line_no, row in rows[1:]:
        if len(row) < width:
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        body.append(row)
        rowids.append(line_no)

    if not body:
        raise DataGateError(
            400, "non-tabular content: need at least one header row and one data row"
        )
    return header, body, rowids


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------
def infer(value: str):
    """Integers and decimals become JSON numbers; everything else stays text."""
    text = value.strip()
    if not text:
        return text
    if INT_RE.match(text):
        try:
            return int(text)
        except ValueError:
            return text
    if DEC_RE.match(text):
        try:
            number = float(text)
        except ValueError:
            return text
        if number == number and number not in (float("inf"), float("-inf")):
            return number
        return text
    return text


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/convert", methods=["GET"])
def convert():
    source = request.args.get("source", "")
    if not source:
        raise DataGateError(400, "missing required query parameter: source")
    validate_url(source)

    charset = request.args.get("charset") or None
    if charset is not None:
        validate_charset(charset)

    data = fetch(source)
    text = decode(data, charset)
    columns, rows, rowids = parse_table(text)
    typed = [[infer(cell) for cell in row] for row in rows]

    identifier = dataset_id(source)
    with _STORE_LOCK:
        _STORE[identifier] = {
            "source": source,
            "columns": columns,
            "rows": typed,
            "rowids": rowids,
        }

    return jsonify({"ok": True, "endpoint": f"/datasets/{identifier}"})


@app.route("/datasets/<dataset>", methods=["GET"])
def query_dataset(dataset: str):
    started = time.perf_counter()
    with _STORE_LOCK:
        stored = _STORE.get(dataset)
    if stored is None:
        raise DataGateError(404, f"unknown dataset id: {dataset}")

    raw = {name: _control(name) for name in CONTROL_PARAMS}

    size = _bounded_int("_size", raw["_size"], 1, ROW_LIMIT)
    offset = _bounded_int("_offset", raw["_offset"], 0, 0)
    shape = _shape(raw["_shape"])
    hide_rowid = _toggle("_rowid", raw["_rowid"])
    hide_total = _toggle("_total", raw["_total"])

    columns, rows, rowids = stored["columns"], stored["rows"], stored["rowids"]

    # Both sort parameters are validated even though only one can take effect.
    ascending = _sort_column("_sort", raw["_sort"], columns)
    descending = _sort_column("_sort_desc", raw["_sort_desc"], columns)

    order = list(range(len(rows)))
    if descending is not None:  # spec: _sort_desc wins
        order.sort(key=lambda i: _order_key(rows[i][descending]), reverse=True)
    elif ascending is not None:
        order.sort(key=lambda i: _order_key(rows[i][ascending]))

    window = order[offset : offset + size]
    if shape == "objects":
        out = []
        for i in window:
            row = {} if hide_rowid else {"rowid": rowids[i]}
            row.update(zip(columns, rows[i]))
            out.append(row)
    else:
        out = [rows[i] for i in window]

    payload = {"ok": True, "columns": columns, "rows": out}
    if not hide_total:
        payload["total"] = len(rows)  # row count before pagination
    payload["query_ms"] = max(0.0, round((time.perf_counter() - started) * 1000.0, 3))
    return jsonify(payload)


def _control(name: str) -> str | None:
    """One value at most: any repeated control parameter is a 400."""
    values = request.args.getlist(name)
    if len(values) > 1:
        raise DataGateError(400, f"repeated control parameter: {name}")
    return values[0] if values else None


def _bounded_int(name: str, raw: str | None, minimum: int, default: int) -> int:
    if raw is None:
        return default
    if not UINT_RE.match(raw) or int(raw) < minimum:
        raise DataGateError(
            400, f"invalid {name}: expected an integer >= {minimum}, got {raw!r}"
        )
    return int(raw)


def _shape(raw: str | None) -> str:
    if raw is None:
        return "lists"
    if raw not in SHAPES:
        raise DataGateError(
            400, f"invalid _shape: expected 'lists' or 'objects', got {raw!r}"
        )
    return raw


def _toggle(name: str, raw: str | None) -> bool:
    """A visibility toggle accepts exactly one value: `hide`."""
    if raw is None:
        return False
    if raw != "hide":
        raise DataGateError(
            400, f"invalid {name}: the only accepted value is 'hide', got {raw!r}"
        )
    return True


def _sort_column(name: str, raw: str | None, columns: list[str]) -> int | None:
    if raw is None:
        return None
    if not raw:
        raise DataGateError(400, f"invalid {name}: a column name is required")
    if raw not in columns:
        raise DataGateError(400, f"unknown column in {name}: {raw!r}")
    return columns.index(raw)


def _order_key(value):
    """A total order over stored values: numbers first, then text."""
    if isinstance(value, bool):
        return (1, 0, str(value))
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0, str(value))


# ---------------------------------------------------------------------------
# Envelope, CORS, and error handling
# ---------------------------------------------------------------------------
@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.before_request
def answer_preflight():
    """Any OPTIONS request is a browser preflight; never let it 404/405."""
    if request.method == "OPTIONS":
        return Response(status=204)
    return None


@app.errorhandler(DataGateError)
def handle_datagate_error(exc: DataGateError):
    return error(exc.status, exc.message)


@app.errorhandler(HTTPException)
def handle_http_exception(exc: HTTPException):
    message = exc.description or exc.name
    response = error(exc.code or 500, message)
    if exc.code == 405 and exc.get_response().headers.get("Allow"):
        response.headers["Allow"] = exc.get_response().headers["Allow"]
    return response


@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):
    return error(500, f"internal error: {exc.__class__.__name__}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagate", description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    subparsers = parser.add_subparsers(dest="command")
    start = subparsers.add_parser("start", help="run the HTTP service")
    start.add_argument("--port", type=int, default=argparse.SUPPRESS)
    start.add_argument("--address", default=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

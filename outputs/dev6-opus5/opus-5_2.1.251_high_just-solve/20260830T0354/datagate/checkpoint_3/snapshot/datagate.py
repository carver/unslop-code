#!/usr/bin/env python3
"""datagate -- turn remote CSV files into queryable JSON datasets.

Usage:
    python datagate.py start --port 8001 --address 127.0.0.1
"""

from __future__ import annotations

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
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"
DEFAULT_ROW_LIMIT = 100
CONTROL_PARAMS = (
    "_size",
    "_offset",
    "_shape",
    "_sort",
    "_sort_desc",
    "_rowid",
    "_total",
    "_timeout_ms",
)
SHAPES = ("lists", "objects")
COMPARATORS = ("exact", "contains", "less", "greater")
NUMERIC_COMPARATORS = ("less", "greater")
# "<column>__<comparator>=<value>"; the column may itself contain the separator,
# so the *last* occurrence is the one that introduces the comparator.
FILTER_SEPARATOR = "__"
DEFAULT_QUERY_TIMEOUT_MS = 5000
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT = 30
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]

app = Flask(__name__)
app.url_map.strict_slashes = False

# id -> {"source": str, "columns": [...], "rows": [[...], ...]}
_DATASETS: dict[str, dict] = {}
_LOCK = threading.Lock()


class DataGateError(Exception):
    """An error that maps onto a JSON error response."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# response helpers
# --------------------------------------------------------------------------


def ok(payload: dict, status: int = 200):
    body = {"ok": True}
    body.update(payload)
    return jsonify(body), status


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"
    return response


@app.errorhandler(HTTPException)
def handle_http_exception(exc: HTTPException):
    if exc.code == 404:
        message = "not found"
    elif exc.code == 405:
        message = "method not allowed"
    else:
        message = exc.description or exc.name
    return fail(message, exc.code or 500)


@app.errorhandler(DataGateError)
def handle_datagate_error(exc: DataGateError):
    return fail(exc.message, exc.status)


@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):  # pragma: no cover - safety net
    if isinstance(exc, HTTPException):
        return handle_http_exception(exc)
    return fail("internal server error: %s" % exc, 500)


# --------------------------------------------------------------------------
# url / charset validation
# --------------------------------------------------------------------------


def validate_source(source: str) -> str:
    if source is None:
        raise DataGateError("missing required query parameter: source", 400)
    source = source.strip()
    if not source:
        raise DataGateError("missing required query parameter: source", 400)
    try:
        parsed = urlparse(source)
    except ValueError:
        raise DataGateError("invalid url: %s" % source, 400)
    if parsed.scheme.lower() not in ("http", "https"):
        raise DataGateError(
            "invalid url: only http and https urls are supported", 400
        )
    if not parsed.netloc or not parsed.hostname:
        raise DataGateError("invalid url: missing host", 400)
    if any(ch.isspace() for ch in source):
        raise DataGateError("invalid url: whitespace is not allowed", 400)
    return source


def validate_charset(charset):
    """Return a normalised codec name, or None when no charset was supplied."""
    if charset is None:
        return None
    charset = charset.strip()
    if not charset:
        return None
    try:
        info = codecs.lookup(charset)
    except (LookupError, TypeError, ValueError):
        raise DataGateError("unsupported or malformed charset: %s" % charset, 400)
    return info.name


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------


def fetch(source: str) -> bytes:
    try:
        response = requests.get(
            source,
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
            stream=True,
        )
    except requests.RequestException as exc:
        raise DataGateError("source unreachable: %s" % exc, 404)
    try:
        if response.status_code >= 400:
            raise DataGateError(
                "remote http error: %d for %s" % (response.status_code, source), 404
            )
        chunks = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise DataGateError("source is too large to process", 400)
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise DataGateError("source unreachable: %s" % exc, 404)
        return b"".join(chunks)
    finally:
        response.close()


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------

_BOMS = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]


def decode_with_charset(data: bytes, charset: str) -> str:
    try:
        return data.decode(charset)
    except (UnicodeDecodeError, LookupError, ValueError) as exc:
        raise DataGateError(
            "unsupported or malformed charset: cannot decode content as %s (%s)"
            % (charset, exc),
            400,
        )


def detect_and_decode(data: bytes) -> str:
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                break
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            encoding = best.encoding
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                return str(best)
    except Exception:
        pass
    for encoding in ("cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# csv parsing
# --------------------------------------------------------------------------


def _looks_non_tabular(text: str, raw: bytes) -> None:
    stripped = text.strip().lstrip("﻿").strip()
    if not stripped:
        raise DataGateError("non-tabular content: source is empty", 400)
    if "\x00" in text:
        raise DataGateError("non-tabular content: source is binary", 400)
    if stripped[0] == "<":
        raise DataGateError(
            "non-tabular content: source looks like markup, not tabular data", 400
        )
    if stripped[0] in "{[":
        try:
            json.loads(stripped)
        except ValueError:
            pass
        else:
            raise DataGateError(
                "non-tabular content: source looks like json, not tabular data", 400
            )
    if raw[:4] in (b"%PDF", b"PK\x03\x04") or raw[:2] == b"\x1f\x8b":
        raise DataGateError("non-tabular content: source is binary", 400)


def _parse_rows(text: str, delimiter: str):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = []
    try:
        for row in reader:
            if not row or all(cell.strip() == "" for cell in row):
                continue
            rows.append(row)
    except csv.Error as exc:
        raise DataGateError("non-tabular content: %s" % exc, 400)
    return rows


MIN_CONSISTENCY = 0.5


def _score(rows) -> tuple:
    """Higher is better: (has_columns, consistency, column_count).

    ``consistency`` is the share of rows whose field count matches the header;
    a real delimiter splits every row the same way, a coincidental one does not.
    """
    if len(rows) < 2:
        return (0, 0.0, 0)
    header_len = len(rows[0])
    if header_len < 2:
        return (0, 0.0, header_len)
    matching = sum(1 for row in rows if len(row) == header_len)
    consistency = matching / len(rows)
    return (1, round(consistency, 6), header_len)


def sniff_and_parse(text: str, raw: bytes):
    """Return (columns, rows) parsed with the inferred delimiter."""
    _looks_non_tabular(text, raw)

    text = text.lstrip("﻿")

    best = None
    best_key = None
    for index, delimiter in enumerate(CANDIDATE_DELIMITERS):
        try:
            rows = _parse_rows(text, delimiter)
        except DataGateError:
            continue
        score = _score(rows)
        # prefer earlier delimiters on ties (deterministic)
        key = (score[0], score[1], score[2], -index)
        if best_key is None or key > best_key:
            best_key = key
            best = rows

    if best is None or best_key is None or best_key[0] == 0 or best_key[1] < MIN_CONSISTENCY:
        # No delimiter produced a consistent multi-column table.
        try:
            lines = _parse_rows(text, ",")
        except DataGateError:
            lines = []
        if len(lines) < 2:
            raise DataGateError(
                "non-tabular content: a valid file requires at least one header row "
                "and one data row",
                400,
            )
        raise DataGateError(
            "non-tabular content: could not infer a delimiter (',', ';' or tab) "
            "producing a consistent table",
            400,
        )

    rows = best

    header = [cell.strip().lstrip("﻿") for cell in rows[0]]
    width = len(header)
    data_rows = []
    for row in rows[1:]:
        if len(row) < width:
            row = list(row) + [""] * (width - len(row))
        elif len(row) > width:
            row = list(row[:width])
        data_rows.append([convert_value(cell) for cell in row])

    if not data_rows:
        raise DataGateError(
            "non-tabular content: a valid file requires at least one header row "
            "and one data row",
            400,
        )
    return header, data_rows


# --------------------------------------------------------------------------
# type inference
# --------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")
_DEC_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)$")
_SCI_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?$")


def convert_value(value: str):
    """Deterministically convert a raw CSV cell to a JSON-friendly value."""
    if value is None:
        return ""
    text = value.strip()
    if not text:
        return ""
    # time-like values (08:30, 9:15, 12:00, 12:00:30) stay text
    if ":" in text or _TIME_RE.match(text):
        return text
    if _INT_RE.match(text):
        try:
            return int(text)
        except ValueError:
            return text
    if _DEC_RE.match(text) or _SCI_RE.match(text):
        try:
            number = float(text)
        except ValueError:
            return text
        if math.isfinite(number):
            return number
        return text
    return text


# --------------------------------------------------------------------------
# dataset identity / storage
# --------------------------------------------------------------------------


def dataset_id(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


@app.route("/convert", methods=["GET", "OPTIONS"])
def convert():
    if request.method == "OPTIONS":
        return ("", 204)

    if "source" not in request.args:
        raise DataGateError("missing required query parameter: source", 400)
    source = validate_source(request.args.get("source"))
    charset = validate_charset(request.args.get("charset"))

    raw = fetch(source)
    if charset:
        text = decode_with_charset(raw, charset)
    else:
        text = detect_and_decode(raw)

    columns, rows = sniff_and_parse(text, raw)

    ident = dataset_id(source)
    with _LOCK:
        _DATASETS[ident] = {"source": source, "columns": columns, "rows": rows}

    return ok({"endpoint": "/datasets/%s" % ident})


# --------------------------------------------------------------------------
# control parameters (pagination, sorting, response shape)
# --------------------------------------------------------------------------

_SIGNED_INT_RE = re.compile(r"^[+-]?\d+$")


def single_param(name: str):
    """Return the sole value given for a control parameter, else ``None``.

    Supplying a control parameter more than once is ambiguous, so it is an
    error rather than a silent "last one wins".
    """
    values = request.args.getlist(name)
    if len(values) > 1:
        raise DataGateError(
            "invalid %s: repeated query parameter, %s may only be given once"
            % (name, name),
            400,
        )
    return values[0] if values else None


def parse_bounded_int(raw: str, name: str, minimum: int, described: str) -> int:
    text = raw.strip()
    if not _SIGNED_INT_RE.match(text):
        raise DataGateError("invalid %s: %s must be %s" % (name, name, described), 400)
    value = int(text)
    if value < minimum:
        raise DataGateError("invalid %s: %s must be %s" % (name, name, described), 400)
    return value


def parse_hide_toggle(raw, name: str) -> bool:
    """``_rowid``/``_total`` accept only the literal value ``hide``."""
    if raw is None:
        return False
    if raw != "hide":
        raise DataGateError(
            "invalid %s: the only supported value is 'hide'" % name, 400
        )
    return True


def parse_shape(raw) -> str:
    if raw is None:
        return "lists"
    if raw not in SHAPES:
        raise DataGateError(
            "invalid _shape: expected one of %s" % ", ".join(SHAPES), 400
        )
    return raw


def resolve_sort(columns):
    """Return ``(column_index, descending)`` or ``None`` when unsorted.

    ``_sort_desc`` wins when both are supplied, but both are still validated:
    naming a column that does not exist is an error either way.
    """
    ascending = single_param("_sort")
    descending = single_param("_sort_desc")

    chosen = None
    for raw, name, reverse in ((ascending, "_sort", False), (descending, "_sort_desc", True)):
        if raw is None:
            continue
        if not raw:
            raise DataGateError("invalid %s: column name must not be empty" % name, 400)
        if raw not in columns:
            raise DataGateError("invalid %s: unknown column: %s" % (name, raw), 400)
        chosen = (columns.index(raw), reverse)
    return chosen


def sort_key(value):
    """Order mixed CSV cell types deterministically: blanks, numbers, text.

    A column can hold both numbers and text, which Python refuses to compare,
    so every cell is mapped onto a uniform ``(rank, number, text)`` tuple.
    """
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, (int, float)):
        return (1, float(value), "")
    text = str(value)
    if not text:
        return (0, 0.0, "")
    return (2, 0.0, text)


def legacy_int_param(name: str, default: int) -> int:
    """Support the pre-existing ``limit``/``offset`` spelling."""
    raw = request.args.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise DataGateError("invalid %s: %s" % (name, raw), 400)
    if value < 0:
        raise DataGateError("invalid %s: %s" % (name, raw), 400)
    return value


# --------------------------------------------------------------------------
# column-level filtering
# --------------------------------------------------------------------------


def cell_text(value) -> str:
    """The string form a cell is compared against by ``exact``/``contains``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def cell_number(value):
    """Return ``value`` as a float, or ``None`` when it does not parse as one.

    Stored cells arrive already typed by :func:`convert_value`, but a column may
    still mix numbers with text; a cell that is not numeric simply never matches
    a numeric comparator.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class QueryBudget:
    """Wall-clock ceiling on a single ``/datasets`` query."""

    def __init__(self, started: float, limit_ms):
        self.started = started
        self.limit_ms = limit_ms

    def elapsed_ms(self) -> float:
        return max(0.0, (time.perf_counter() - self.started) * 1000.0)

    def check(self) -> None:
        if self.limit_ms is None:
            return
        elapsed = self.elapsed_ms()
        if elapsed > self.limit_ms:
            raise DataGateError(
                "query timeout: the query exceeded its %s ms time limit "
                "(%.1f ms elapsed)" % (self.limit_ms, elapsed),
                400,
            )


def resolve_timeout_ms():
    raw = single_param("_timeout_ms")
    if raw is None:
        return DEFAULT_QUERY_TIMEOUT_MS
    return parse_bounded_int(
        raw, "_timeout_ms", 0, "a non-negative integer number of milliseconds"
    )


def parse_filters(columns):
    """Turn ``<column>__<comparator>=<value>`` query params into filter specs.

    Returns a list of ``(column_index, comparator, value, number)`` tuples;
    ``number`` is the pre-parsed float for the numeric comparators and ``None``
    otherwise. Anything that is not filter-shaped is ignored rather than
    rejected, so control parameters and stray extras still pass through.
    """
    filters = []
    seen = set()
    for key in request.args.keys():
        if key in seen:
            continue
        seen.add(key)
        if key.startswith("_"):
            # a control parameter, never a filter
            continue
        if FILTER_SEPARATOR not in key:
            # not filter-shaped, ignored
            continue

        values = request.args.getlist(key)
        if len(values) > 1:
            raise DataGateError(
                "invalid filter %s: repeated filter parameter, %s may only be "
                "given once" % (key, key),
                400,
            )

        column, _, comparator = key.rpartition(FILTER_SEPARATOR)
        if comparator not in COMPARATORS:
            raise DataGateError(
                "invalid filter %s: unknown comparator: %s (expected one of %s)"
                % (key, comparator, ", ".join(COMPARATORS)),
                400,
            )
        if column not in columns:
            raise DataGateError(
                "invalid filter %s: unknown column: %s" % (key, column), 400
            )

        value = values[0]
        number = None
        if comparator in NUMERIC_COMPARATORS:
            number = cell_number(value)
            if number is None:
                raise DataGateError(
                    "invalid filter %s: __%s requires a numeric value, got: %s"
                    % (key, comparator, value),
                    400,
                )
        filters.append((columns.index(column), comparator, value, number))
    return filters


def row_matches(row, filters) -> bool:
    """Every filter must hold: multiple filters are ANDed."""
    for index, comparator, value, number in filters:
        cell = row[index]
        if comparator == "exact":
            if cell_text(cell) != value:
                return False
        elif comparator == "contains":
            if value not in cell_text(cell):
                return False
        else:
            stored = cell_number(cell)
            if stored is None:
                return False
            if comparator == "less":
                if not stored < number:
                    return False
            elif not stored > number:
                return False
    return True


FILTER_BUDGET_STRIDE = 512


def apply_filters(numbered, filters, budget: QueryBudget):
    budget.check()
    if not filters:
        return numbered
    kept = []
    for position, pair in enumerate(numbered):
        if position % FILTER_BUDGET_STRIDE == 0:
            budget.check()
        if row_matches(pair[1], filters):
            kept.append(pair)
    budget.check()
    return kept


@app.route("/datasets/<dataset>", methods=["GET", "OPTIONS"])
def get_dataset(dataset: str):
    if request.method == "OPTIONS":
        return ("", 204)

    started = time.perf_counter()
    with _LOCK:
        stored = _DATASETS.get(dataset)
    if stored is None:
        raise DataGateError("unknown dataset: %s" % dataset, 404)

    columns = list(stored["columns"])

    budget = QueryBudget(started, resolve_timeout_ms())

    shape = parse_shape(single_param("_shape"))
    hide_rowid = parse_hide_toggle(single_param("_rowid"), "_rowid")
    hide_total = parse_hide_toggle(single_param("_total"), "_total")
    sort = resolve_sort(columns)
    filters = parse_filters(columns)

    raw_size = single_param("_size")
    if raw_size is None:
        size = legacy_int_param("limit", DEFAULT_ROW_LIMIT)
    else:
        size = parse_bounded_int(raw_size, "_size", 1, "a positive integer")

    raw_offset = single_param("_offset")
    if raw_offset is None:
        offset = legacy_int_param("offset", 0)
    else:
        offset = parse_bounded_int(raw_offset, "_offset", 0, "a non-negative integer")

    # rowid is the 1-based position in the source file, so it is attached before
    # filtering and sorting and survives both.
    numbered = list(enumerate(stored["rows"], start=1))

    # filtering precedes sorting, and total counts the filtered rows before the
    # pagination window is taken.
    numbered = apply_filters(numbered, filters, budget)
    total = len(numbered)

    if sort is not None:
        index, reverse = sort
        # list.sort is stable, and stays stable under reverse=True: equal keys
        # keep their source-file order rather than being flipped.
        numbered.sort(key=lambda pair: sort_key(pair[1][index]), reverse=reverse)
        budget.check()

    window = numbered[offset : offset + size]

    if shape == "objects":
        rows = []
        for rowid, row in window:
            record = {"rowid": rowid} if not hide_rowid else {}
            record.update(zip(columns, row))
            rows.append(record)
    else:
        rows = [list(row) for _, row in window]

    query_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    payload = {"columns": columns, "rows": rows}
    if not hide_total:
        payload["total"] = total
    payload["query_ms"] = round(query_ms, 4)
    return ok(payload)


@app.route("/", methods=["GET", "OPTIONS"])
def index():
    if request.method == "OPTIONS":
        return ("", 204)
    return ok(
        {
            "service": "datagate",
            "endpoints": ["/convert?source=<url>[&charset=<charset>]", "/datasets/<id>"],
        }
    )


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datagate", description=__doc__)
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="start the datagate http server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in (None, "start"):
        parser.error("unknown command: %s" % args.command)
    app.run(host=args.address, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

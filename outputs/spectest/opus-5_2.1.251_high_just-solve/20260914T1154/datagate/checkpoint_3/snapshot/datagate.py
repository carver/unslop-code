"""datagate -- fetch remote CSV files and serve them as JSON datasets."""

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
from collections import Counter
from urllib.parse import urlsplit

import requests
from flask import Flask, Response, g, jsonify, request

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"

DEFAULT_ROW_LIMIT = 100
MAX_SAMPLE_LINES = 100
FETCH_TIMEOUT = 30
MAX_BYTES = 64 * 1024 * 1024

# Wall-clock budget for evaluating a single /datasets/<id> query.
QUERY_TIMEOUT_SECONDS = 15.0

# How often the query budget is re-checked while scanning rows.
TIMEOUT_CHECK_INTERVAL = 512

# `,`, `;` and `\t` are the required minimum; the rest are best effort.
DELIMITERS = [",", ";", "\t", "|", ":"]

ALLOWED_SCHEMES = ("http", "https")

# --------------------------------------------------------------------------- #
# Dataset store
# --------------------------------------------------------------------------- #

_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()


def dataset_id_for(source: str) -> str:
    """Stable id for a source URL string (identical across processes/restarts)."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def store_dataset(dataset_id: str, payload: dict) -> None:
    with _STORE_LOCK:
        _STORE[dataset_id] = payload


def load_dataset(dataset_id: str):
    with _STORE_LOCK:
        return _STORE.get(dataset_id)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DataGateError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


class BadRequest(DataGateError):
    def __init__(self, message: str):
        super().__init__(message, 400)


class NotFound(DataGateError):
    def __init__(self, message: str):
        super().__init__(message, 404)


class QueryTimeout(BadRequest):
    """Raised when evaluating a request exceeds the query budget."""

    def __init__(self, message: str | None = None):
        super().__init__(message or (
            f"Query timeout: the request exceeded the "
            f"{QUERY_TIMEOUT_SECONDS:g}s query budget."
        ))


# --------------------------------------------------------------------------- #
# URL validation
# --------------------------------------------------------------------------- #


def validate_url(raw: str) -> str:
    candidate = (raw or "").strip()
    if not candidate:
        raise BadRequest("Query parameter 'source' is required.")
    try:
        parts = urlsplit(candidate)
    except ValueError:
        raise BadRequest(f"Invalid URL: {raw!r}")

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BadRequest(
            "Invalid URL: 'source' must be an absolute http:// or https:// URL."
        )
    try:
        hostname = parts.hostname
    except ValueError:
        raise BadRequest(f"Invalid URL: {raw!r}")
    if not hostname:
        raise BadRequest("Invalid URL: missing host in 'source'.")
    if any(ch.isspace() for ch in candidate):
        raise BadRequest("Invalid URL: whitespace is not allowed.")
    try:
        parts.port
    except ValueError:
        raise BadRequest("Invalid URL: invalid port in 'source'.")
    return candidate


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #


def fetch_source(url: str) -> bytes:
    try:
        response = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "datagate/1.0", "Accept": "*/*"},
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise NotFound(f"Source unreachable: {exc.__class__.__name__}")
    except Exception as exc:  # pragma: no cover - defensive
        raise NotFound(f"Source unreachable: {exc}")

    try:
        if response.status_code >= 400:
            raise NotFound(
                f"Remote server returned HTTP {response.status_code} for the source URL."
            )
        try:
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    break
            return b"".join(chunks)[:MAX_BYTES]
        except requests.exceptions.RequestException as exc:
            raise NotFound(f"Source unreachable: {exc.__class__.__name__}")
    finally:
        response.close()


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #

BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def validate_charset(charset: str) -> str:
    name = (charset or "").strip()
    if not name:
        raise BadRequest("Unsupported charset: charset must be a non-empty name.")
    try:
        return codecs.lookup(name).name
    except (LookupError, TypeError, ValueError):
        raise BadRequest(f"Unsupported charset: {charset!r}")


def decode_with_charset(data: bytes, charset: str) -> str:
    codec = validate_charset(charset)
    try:
        text = data.decode(codec, errors="strict")
    except (UnicodeDecodeError, LookupError, ValueError) as exc:
        raise BadRequest(f"Malformed charset: cannot decode content as {charset!r} ({exc}).")
    return strip_bom(text)


def strip_bom(text: str) -> str:
    return text[1:] if text.startswith("﻿") else text


def detect_decode(data: bytes) -> str:
    """Best-effort encoding detection for the raw CSV bytes."""
    for bom, codec in BOMS:
        if data.startswith(bom):
            try:
                return strip_bom(data.decode(codec))
            except UnicodeDecodeError:
                break

    try:
        return strip_bom(data.decode("utf-8"))
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            encoding = best.encoding
            try:
                return strip_bom(data.decode(encoding, errors="strict"))
            except (UnicodeDecodeError, LookupError):
                return strip_bom(str(best))
    except Exception:
        pass

    for codec in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return strip_bom(data.decode(codec, errors="strict"))
        except (UnicodeDecodeError, LookupError, ValueError):
            continue
    return strip_bom(data.decode("latin-1", errors="replace"))


# --------------------------------------------------------------------------- #
# CSV parsing
# --------------------------------------------------------------------------- #


def looks_binary(data: bytes) -> bool:
    head = data[:8192]
    if not head:
        return False
    for bom, _ in BOMS:
        if data.startswith(bom):
            return False
    if b"\x00" in head:
        return True
    control = sum(1 for b in head if b < 9 or (13 < b < 32))
    return control / len(head) > 0.05


def looks_markup_or_json(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return True
    if stripped[0] == "<":
        return True
    if stripped[:1] in ("{", "["):
        try:
            json.loads(text)
            return True
        except (ValueError, RecursionError):
            return False
    return False


def parse_rows(text: str, delimiter: str, limit: int | None = None) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter,
                        quotechar='"', skipinitialspace=False)
    rows: list[list[str]] = []
    try:
        for row in reader:
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    except csv.Error:
        pass
    return rows


def is_blank_row(row: list[str]) -> bool:
    return not row or all((cell or "").strip() == "" for cell in row)


def score_delimiter(text: str, delimiter: str):
    """Return (consistency, column_count) for parsing `text` with `delimiter`."""
    rows = [r for r in parse_rows(text, delimiter, limit=MAX_SAMPLE_LINES)
            if not is_blank_row(r)]
    if len(rows) < 2:
        return None
    header_len = len(rows[0])
    if header_len < 2:
        return None
    counts = Counter(len(r) for r in rows)
    matching = counts.get(header_len, 0)
    consistency = matching / len(rows)
    return (consistency, header_len)


def sniff_delimiter(text: str) -> str | None:
    best = None
    best_delim = None
    for delim in DELIMITERS:
        score = score_delimiter(text, delim)
        if score is None:
            continue
        if best is None or score > best:
            best, best_delim = score, delim
    if best is None or best[0] < 0.5:
        return None
    return best_delim


def normalise_columns(header: list[str]) -> list[str]:
    columns: list[str] = []
    for index, raw in enumerate(header):
        name = strip_bom((raw or "").strip())
        if not name:
            name = f"column_{index + 1}"
        columns.append(name)
    return columns


def parse_csv(text: str) -> tuple[list[str], list[list]]:
    if looks_markup_or_json(text):
        raise BadRequest("Non-tabular content: the source does not look like a CSV file.")

    delimiter = sniff_delimiter(text)
    if delimiter is None:
        raise BadRequest(
            "Non-tabular content: unable to infer a delimiter or the file has no "
            "header row and at least one data row."
        )

    rows = [r for r in parse_rows(text, delimiter) if not is_blank_row(r)]
    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: a valid file requires a header row and at least "
            "one data row."
        )

    columns = normalise_columns(rows[0])
    width = len(columns)
    if width < 2:
        raise BadRequest("Non-tabular content: no tabular structure detected.")

    data_rows: list[list] = []
    for raw_row in rows[1:]:
        cells = list(raw_row[:width])
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        data_rows.append([coerce_value(cell) for cell in cells])

    if not data_rows:
        raise BadRequest(
            "Non-tabular content: a valid file requires a header row and at least "
            "one data row."
        )
    return columns, data_rows


# --------------------------------------------------------------------------- #
# Type inference (deterministic, locale independent)
# --------------------------------------------------------------------------- #

INT_RE = re.compile(r"^[+-]?\d+$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*(?:[AaPp]\.?[Mm]\.?)?$")


def coerce_value(raw):
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return value

    # Time-like values stay text (08:30, 9:15, 12:00, 08:30:05, 8:30 PM).
    if TIME_RE.match(value):
        return str(raw)

    digits = value.lstrip("+-")

    if INT_RE.match(value):
        # Preserve identifier-ish values such as "007" or "0123" as text.
        if len(digits) > 1 and digits[0] == "0":
            return str(raw)
        try:
            return int(value)
        except ValueError:
            return str(raw)

    if DECIMAL_RE.match(value):
        integer_part = digits.split(".")[0].split("e")[0].split("E")[0]
        if len(integer_part) > 1 and integer_part[0] == "0":
            return str(raw)
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return str(raw)
        if math.isnan(number) or math.isinf(number):
            return str(raw)
        return number

    return str(raw)


# --------------------------------------------------------------------------- #
# Response controls (pagination, sorting, shape)
# --------------------------------------------------------------------------- #

CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc",
                  "_rowid", "_total")

SHAPES = ("lists", "objects")


def single_value(args, name: str) -> str | None:
    """Return the single value for `name`, or None when absent.

    A control parameter repeated in the query string is a bad request.
    """
    values = args.getlist(name)
    if not values:
        return None
    if len(values) > 1:
        raise BadRequest(
            f"Invalid {name}: parameter may only be supplied once "
            f"({len(values)} values given)."
        )
    return values[0]


def parse_int_param(raw: str, name: str, minimum: int) -> int:
    text = (raw or "").strip()
    kind = "a positive integer" if minimum > 0 else "a non-negative integer"
    if not text or not re.fullmatch(r"[+-]?\d+", text):
        raise BadRequest(f"Invalid {name}: expected {kind}, got {raw!r}.")
    try:
        value = int(text)
    except ValueError:  # pragma: no cover - guarded by the regex above
        raise BadRequest(f"Invalid {name}: expected {kind}, got {raw!r}.")
    if value < minimum:
        raise BadRequest(f"Invalid {name}: expected {kind}, got {raw!r}.")
    return value


def parse_toggle(args, name: str) -> bool:
    """`_rowid`/`_total` accept only the literal value 'hide'."""
    raw = single_value(args, name)
    if raw is None:
        return False
    if raw.strip() != "hide":
        raise BadRequest(f"Invalid {name}: the only supported value is 'hide', "
                         f"got {raw!r}.")
    return True


def parse_shape(args) -> str:
    raw = single_value(args, "_shape")
    if raw is None:
        return "lists"
    shape = raw.strip()
    if shape not in SHAPES:
        raise BadRequest(
            f"Invalid _shape: expected one of {', '.join(SHAPES)}, got {raw!r}."
        )
    return shape


def parse_sort(args, columns: list[str]):
    """Return (column, descending) or (None, False) when unsorted."""
    chosen = None
    for name in ("_sort", "_sort_desc"):
        raw = single_value(args, name)
        if raw is None:
            continue
        column = raw.strip()
        if not column:
            raise BadRequest(f"Invalid {name}: a column name is required.")
        if column not in columns:
            raise BadRequest(f"Invalid {name}: unknown column {raw!r}.")
        # `_sort_desc` is checked last, so it wins when both are present.
        chosen = (column, name == "_sort_desc")
    return chosen if chosen is not None else (None, False)


def sort_key(value):
    """Order values deterministically across mixed types: blanks, numbers, text."""
    if value is None:
        return (0, 0, "")
    if isinstance(value, bool):
        return (1, int(value), "")
    if isinstance(value, (int, float)):
        return (1, value, "")
    text = str(value)
    if not text.strip():
        return (0, 0, "")
    return (2, 0, text)


# --------------------------------------------------------------------------- #
# Column-level filtering
# --------------------------------------------------------------------------- #

# Filters are written `<column>__<comparator>=<value>`; the comparator is the
# part after the *last* separator so that columns containing `__` still work.
FILTER_SEPARATOR = "__"

COMPARATORS = ("exact", "contains", "less", "greater")

NUMERIC_COMPARATORS = ("less", "greater")


def filter_text(value) -> str:
    """Render a stored cell the way `exact`/`contains` compare it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def filter_number(value):
    """Parse a stored cell or filter value as a float, or None when not numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_filters(args, columns: list[str]) -> list[tuple]:
    """Validate `<column>__<comparator>=<value>` params into matcher tuples.

    Control parameters (`_`-prefixed) and params without the separator are not
    filters and are ignored here.
    """
    filters: list[tuple] = []
    for key in args.keys():
        if key.startswith("_") or FILTER_SEPARATOR not in key:
            continue

        values = args.getlist(key)
        if len(values) > 1:
            raise BadRequest(
                f"Invalid filter {key!r}: duplicate filter key "
                f"({len(values)} values given)."
            )

        column, _, comparator = key.rpartition(FILTER_SEPARATOR)
        if comparator not in COMPARATORS:
            raise BadRequest(
                f"Invalid filter {key!r}: unknown comparator {comparator!r}, "
                f"expected one of {', '.join(COMPARATORS)}."
            )
        if column not in columns:
            raise BadRequest(f"Invalid filter {key!r}: unknown column {column!r}.")

        raw = values[0]
        number = None
        if comparator in NUMERIC_COMPARATORS:
            number = filter_number(raw)
            if number is None:
                raise BadRequest(
                    f"Invalid filter {key!r}: __{comparator} requires a numeric "
                    f"value, got {raw!r}."
                )
        filters.append((columns.index(column), comparator, raw, number))
    return filters


def row_matches(row: list, filters: list[tuple]) -> bool:
    """True when `row` satisfies every filter (filters are ANDed)."""
    for index, comparator, raw, number in filters:
        value = row[index] if index < len(row) else ""
        if comparator == "exact":
            if filter_text(value) != raw:
                return False
        elif comparator == "contains":
            if raw not in filter_text(value):
                return False
        else:
            # Rows whose stored value is not numeric never match.
            stored = filter_number(value)
            if stored is None:
                return False
            if comparator == "less":
                if not stored < number:
                    return False
            elif not stored > number:
                return False
    return True


def check_deadline(deadline: float) -> None:
    if time.perf_counter() > deadline:
        raise QueryTimeout()


def apply_filters(numbered: list[tuple], filters: list[tuple],
                  deadline: float) -> list[tuple]:
    check_deadline(deadline)
    if not filters:
        return numbered
    selected = []
    for position, item in enumerate(numbered):
        if position % TIMEOUT_CHECK_INTERVAL == 0:
            check_deadline(deadline)
        if row_matches(item[1], filters):
            selected.append(item)
    check_deadline(deadline)
    return selected


# --------------------------------------------------------------------------- #
# Flask application
# --------------------------------------------------------------------------- #


def add_cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    def error(message: str, status: int):
        return jsonify({"ok": False, "error": message}), status

    @app.before_request
    def _start_timer():
        g.started_at = time.perf_counter()

    @app.after_request
    def _cors(response: Response):
        return add_cors(response)

    @app.route("/convert", methods=["GET", "HEAD", "OPTIONS"])
    def convert():
        if request.method == "OPTIONS":
            return Response(status=204)

        if "source" not in request.args:
            return error("Query parameter 'source' is required.", 400)

        try:
            source_raw = request.args.get("source", "")
            source = validate_url(source_raw)

            charset = None
            if "charset" in request.args:
                charset = request.args.get("charset", "")
                validate_charset(charset)

            dataset_id = dataset_id_for(source_raw)

            payload_bytes = fetch_source(source)
            if not payload_bytes.strip():
                raise BadRequest("Non-tabular content: the source is empty.")

            if charset is not None:
                text = decode_with_charset(payload_bytes, charset)
            else:
                if looks_binary(payload_bytes):
                    raise BadRequest("Non-tabular content: the source is binary data.")
                text = detect_decode(payload_bytes)

            columns, rows = parse_csv(text)
            store_dataset(dataset_id, {"columns": columns, "rows": rows, "source": source_raw})
        except DataGateError as exc:
            return error(exc.message, exc.status)
        except Exception as exc:  # pragma: no cover - defensive
            return error(f"Failed to convert source: {exc}", 400)

        return jsonify({"ok": True, "endpoint": f"/datasets/{dataset_id}"}), 200

    @app.route("/datasets/<dataset_id>", methods=["GET", "HEAD", "OPTIONS"])
    def dataset(dataset_id: str):
        if request.method == "OPTIONS":
            return Response(status=204)

        started = getattr(g, "started_at", time.perf_counter())
        record = load_dataset(dataset_id)
        if record is None:
            return error(f"Unknown dataset id: {dataset_id!r}", 404)

        columns = list(record["columns"])
        try:
            for name in CONTROL_PARAMS:
                single_value(request.args, name)

            shape = parse_shape(request.args)
            hide_rowid = parse_toggle(request.args, "_rowid")
            hide_total = parse_toggle(request.args, "_total")

            raw_size = single_value(request.args, "_size")
            size = (DEFAULT_ROW_LIMIT if raw_size is None
                    else parse_int_param(raw_size, "_size", 1))

            raw_offset = single_value(request.args, "_offset")
            offset = (0 if raw_offset is None
                      else parse_int_param(raw_offset, "_offset", 0))

            sort_column, descending = parse_sort(request.args, columns)
            filters = parse_filters(request.args, columns)

            # Rows are stored with their 1-based source position so that `rowid`
            # survives filtering, sorting and pagination.
            deadline = started + QUERY_TIMEOUT_SECONDS
            numbered = list(enumerate(record["rows"], start=1))

            # Filter first, then sort, then paginate; `total` is the filtered
            # count before pagination.
            numbered = apply_filters(numbered, filters, deadline)
            total = len(numbered)

            if sort_column is not None:
                index = columns.index(sort_column)
                numbered.sort(key=lambda item: sort_key(item[1][index]),
                              reverse=descending)
                check_deadline(deadline)
        except DataGateError as exc:
            return error(exc.message, exc.status)

        window = numbered[offset:offset + size]

        if shape == "objects":
            rows = []
            for rowid, values in window:
                row = {} if hide_rowid else {"rowid": rowid}
                for column, value in zip(columns, values):
                    row[column] = value
                rows.append(row)
        else:
            rows = [list(values) for _, values in window]

        query_ms = max(0.0, round((time.perf_counter() - started) * 1000.0, 3))

        payload = {"ok": True, "columns": columns, "rows": rows}
        if not hide_total:
            payload["total"] = total
        payload["query_ms"] = query_ms
        return jsonify(payload), 200

    @app.route("/", methods=["GET", "HEAD", "OPTIONS"])
    def index():
        if request.method == "OPTIONS":
            return Response(status=204)
        return jsonify({
            "ok": True,
            "service": "datagate",
            "endpoints": ["/convert?source=<url>[&charset=<name>]", "/datasets/<id>"],
            "controls": list(CONTROL_PARAMS),
            "filters": [f"<column>__{name}=<value>" for name in COMPARATORS],
        }), 200

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(500)
    def _json_errors(exc):
        status = getattr(exc, "code", 500) or 500
        if status in (404, 405):
            status, message = 404, "Not found."
        elif status == 400:
            message = "Bad request."
        else:
            message = "Internal server error."
        return error(message, status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        if isinstance(exc, DataGateError):
            return error(exc.message, exc.status)
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            return _json_errors(exc)
        return error(f"Internal server error: {exc}", 500)

    return app


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="datagate", description="datagate server")
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="Start the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)

    if not argv or argv[0].startswith("-"):
        argv = ["start"] + argv

    args = parser.parse_args(argv)
    if args.command != "start":
        parser.print_help()
        return 1

    app = create_app()
    app.run(host=args.address, port=args.port, threaded=True, debug=False,
            use_reloader=False)
    return 0


app = create_app()

if __name__ == "__main__":
    raise SystemExit(main())

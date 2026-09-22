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
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"

DEFAULT_ROW_LIMIT = 100
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT = 30

# Control parameters understood by /datasets/<id>. Every one of them may appear
# at most once per request; anything else in the query string is ignored.
CONTROL_PARAMS = (
    "_size",
    "_offset",
    "_shape",
    "_sort",
    "_sort_desc",
    "_rowid",
    "_total",
)
SHAPES = ("lists", "objects")
HIDE = "hide"

# The first row of the source file is the header, so the first data row is 2.
FIRST_DATA_ROWID = 2

# Minimum required delimiters are "," ";" and "\t"; "|" and ":" are supported
# as a bonus but are only ever chosen when they clearly structure the input.
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
FALLBACK_ENCODING = "latin-1"

_ID_LENGTH = 16

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class DatasetStore:
    """Thread-safe in-memory dataset store keyed by a deterministic id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def make_id(source: str) -> str:
        """Deterministic id derived from the exact source URL string."""
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return digest[:_ID_LENGTH]

    def put(self, dataset_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._data[dataset_id] = payload

    def get(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(dataset_id)


STORE = DatasetStore()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class DataGateError(Exception):
    """An error that maps onto a JSON error envelope."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class BadRequest(DataGateError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 400)


class NotFound(DataGateError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 404)


# --------------------------------------------------------------------------
# URL validation
# --------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"http", "https"}


def validate_source(raw: Optional[str]) -> str:
    """Validate the `source` query parameter and return it unchanged."""
    if raw is None:
        raise BadRequest("Missing required query parameter: 'source'.")
    if not raw.strip():
        raise BadRequest("Query parameter 'source' must not be empty.")

    candidate = raw.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:  # malformed IPv6 literals, bad ports, ...
        raise BadRequest("Invalid URL: %s" % exc) from None

    if not parts.scheme:
        raise BadRequest(
            "Invalid URL: missing scheme (expected an http:// or https:// URL)."
        )
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BadRequest(
            "Invalid URL: unsupported scheme '%s' (expected http or https)."
            % parts.scheme
        )
    if not parts.netloc:
        raise BadRequest("Invalid URL: missing host.")

    hostname = None
    try:
        hostname = parts.hostname
        _ = parts.port  # raises ValueError for a non-numeric / out-of-range port
    except ValueError as exc:
        raise BadRequest("Invalid URL: %s" % exc) from None
    if not hostname:
        raise BadRequest("Invalid URL: missing host.")
    if any(ch.isspace() for ch in candidate):
        raise BadRequest("Invalid URL: URLs must not contain whitespace.")

    # Return the original string: the dataset id is derived from the exact
    # `source` value the caller supplied.
    return raw


# --------------------------------------------------------------------------
# Charset handling
# --------------------------------------------------------------------------


def validate_charset(raw: Optional[str]) -> Optional[str]:
    """Validate an explicit `charset` parameter, returning its codec name."""
    if raw is None:
        return None
    name = raw.strip()
    if not name:
        raise BadRequest("Query parameter 'charset' must not be empty.")
    if len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9._:+()\- ]+", name.replace("_", "")):
        raise BadRequest("Malformed charset: %r." % raw)
    try:
        info = codecs.lookup(name)
    except (LookupError, ValueError, TypeError):
        raise BadRequest("Unsupported charset: %r." % raw) from None

    # Reject non-text codecs such as base64/hex/zlib, which `codecs.lookup`
    # also resolves but which cannot decode bytes into text.
    if not getattr(info, "_is_text_encoding", True):
        raise BadRequest("Unsupported charset: %r." % raw)
    try:
        probe = b"".decode(info.name)
    except Exception:
        raise BadRequest("Unsupported charset: %r." % raw) from None
    if not isinstance(probe, str):
        raise BadRequest("Unsupported charset: %r." % raw)
    return info.name


_BOMS: List[Tuple[bytes, str]] = [
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]


def detect_encoding(data: bytes) -> str:
    """Detect an unambiguous encoding from content, else fall back to latin-1.

    The ladder is fully deterministic: byte-order marks first, then strict
    UTF-8 (a byte sequence that decodes as multi-byte UTF-8 is effectively
    never accidental), then BOM-less UTF-16 detected from NUL padding, and
    finally the latin-1 fallback which never fails.
    """
    if not data:
        return "utf-8"

    for bom, name in _BOMS:
        if data.startswith(bom):
            return name

    # Strict UTF-8 (a superset of ASCII).
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # BOM-less UTF-16: ASCII-dominant text shows a strong NUL pattern in one
    # of the two byte positions.
    sample = data[: 8192 - (8192 % 2)]
    if len(sample) >= 4:
        even_nul = sample[0::2].count(0)
        odd_nul = sample[1::2].count(0)
        half = len(sample) // 2
        if half:
            if odd_nul / half > 0.6 and even_nul == 0:
                try:
                    data.decode("utf-16-le")
                    return "utf-16-le"
                except UnicodeDecodeError:
                    pass
            if even_nul / half > 0.6 and odd_nul == 0:
                try:
                    data.decode("utf-16-be")
                    return "utf-16-be"
                except UnicodeDecodeError:
                    pass

    return FALLBACK_ENCODING


def decode_bytes(data: bytes, charset: Optional[str]) -> str:
    """Decode raw bytes using an explicit charset or a detected one."""
    if charset is not None:
        try:
            text = data.decode(charset)
        except UnicodeDecodeError:
            raise BadRequest(
                "Malformed charset: the source content could not be decoded "
                "as %r." % charset
            ) from None
        except (LookupError, ValueError, TypeError):
            raise BadRequest("Unsupported charset: %r." % charset) from None
    else:
        encoding = detect_encoding(data)
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            text = data.decode(FALLBACK_ENCODING)

    # A UTF-8 BOM can survive an explicit charset such as latin-1.
    if text.startswith("﻿"):
        text = text[1:]
    return text


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def fetch_source(url: str) -> bytes:
    """Download the source URL, mapping every transport failure onto 404."""
    try:
        response = requests.get(
            url.strip(),
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": "datagate/1.0",
                "Accept": "text/csv, text/plain, */*",
            },
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise NotFound("Source unreachable: %s" % _brief(exc)) from None
    except (ValueError, OSError) as exc:
        raise NotFound("Source unreachable: %s" % _brief(exc)) from None

    try:
        if response.status_code >= 400:
            raise NotFound(
                "Remote HTTP error %d for source." % response.status_code
            )
        chunks: List[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    break
        except requests.exceptions.RequestException as exc:
            raise NotFound("Source unreachable: %s" % _brief(exc)) from None
        return b"".join(chunks)[:MAX_DOWNLOAD_BYTES]
    finally:
        response.close()


def _brief(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    text = " ".join(text.split())
    return text[:200]


# --------------------------------------------------------------------------
# Tabular detection & CSV parsing
# --------------------------------------------------------------------------

_CONTROL_ALLOWED = {"\t", "\n", "\r"}


def _looks_like_markup(text: str) -> bool:
    head = text.lstrip()[:4096]
    if not head:
        return False
    lowered = head.lower()
    if lowered.startswith(("<!doctype", "<?xml", "<html", "<rss", "<svg")):
        return True
    if head.startswith("<") and re.match(r"<\s*[A-Za-z!?/]", head):
        return True
    return False


def _looks_like_json(text: str) -> bool:
    head = text.strip()
    if not head or head[0] not in "{[":
        return False
    try:
        json.loads(head)
    except (ValueError, RecursionError):
        return False
    return True


def _looks_binary(text: str, raw: bytes) -> bool:
    if raw.startswith((b"%PDF", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"PK\x03\x04",
                       b"\x1f\x8b", b"BZh", b"\x7fELF", b"MZ", b"RIFF", b"OggS")):
        return True
    sample = text[:8192]
    if not sample:
        return False
    if "\x00" in sample:
        return True
    control = sum(
        1
        for ch in sample
        if (ord(ch) < 32 and ch not in _CONTROL_ALLOWED) or ord(ch) == 127
    )
    return control / len(sample) > 0.02


_PROSE_TERMINATORS = re.compile(r"[.!?](\s|$)")


def _looks_like_prose(rows: List[List[str]]) -> bool:
    """Heuristic guard for single-column parses of free-form text."""
    sample = [r[0] for r in rows[:20] if r and r[0].strip()]
    if not sample:
        return True
    header = sample[0].strip()
    if not header:
        return True
    if _PROSE_TERMINATORS.search(header):
        return True
    if len(header.split()) > 4:
        return True
    wordy = sum(1 for cell in sample if len(cell.split()) > 6)
    return wordy > len(sample) / 2


def _parse_with(text: str, delimiter: str) -> List[List[str]]:
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=delimiter,
        skipinitialspace=True,
    )
    rows: List[List[str]] = []
    try:
        for row in reader:
            rows.append(row)
    except csv.Error:
        return []
    return rows


def _drop_blank_rows(rows: List[List[str]]) -> List[List[str]]:
    return [r for r in rows if any(cell.strip() for cell in r)]


def _score(rows: List[List[str]]) -> Tuple[int, float, int]:
    """Score a candidate parse: (has structure, consistency, width)."""
    if len(rows) < 2:
        return (0, 0.0, 0)
    counts = Counter(len(r) for r in rows)
    width, hits = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    ratio = hits / len(rows)
    return (1 if width > 1 else 0, ratio, width)


def infer_and_parse(text: str) -> Tuple[List[str], List[List[str]]]:
    """Infer the delimiter and parse the document into a header and rows."""
    best: Optional[Tuple[Tuple[int, float, int], int, str, List[List[str]]]] = None

    for index, delimiter in enumerate(CANDIDATE_DELIMITERS):
        parsed = _drop_blank_rows(_parse_with(text, delimiter))
        if not parsed:
            continue
        score = _score(parsed)
        # Lower index wins ties, so `,` beats `;` beats `\t` beats `|`.
        key = (score, -index)
        if best is None or key > (best[0], -best[1]):
            best = (score, index, delimiter, parsed)

    if best is None:
        raise BadRequest(
            "Non-tabular content: the source does not contain a parsable table."
        )

    score, _index, _delimiter, rows = best

    if len(rows) < 2:
        raise BadRequest(
            "Non-tabular content: a valid file requires at least one header "
            "row and one data row."
        )

    header_width = score[2]
    if header_width <= 1:
        # No delimiter present at all: only accept genuinely column-shaped
        # single-column data, not free-form prose.
        if _looks_like_prose(rows):
            raise BadRequest(
                "Non-tabular content: no delimiter could be inferred from the "
                "source."
            )

    header = [cell.strip() for cell in rows[0]]
    if not any(header):
        raise BadRequest("Non-tabular content: the header row is empty.")

    width = len(header)
    data: List[List[str]] = []
    for row in rows[1:]:
        if len(row) < width:
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        data.append([cell.strip() for cell in row])

    if not data:
        raise BadRequest(
            "Non-tabular content: a valid file requires at least one header "
            "row and one data row."
        )
    return header, data


def parse_tabular(raw: bytes, text: str) -> Tuple[List[str], List[List[str]]]:
    if not raw.strip() or not text.strip():
        raise BadRequest("Non-tabular content: the source is empty.")
    if _looks_binary(text, raw):
        raise BadRequest("Non-tabular content: the source appears to be binary.")
    if _looks_like_markup(text):
        raise BadRequest("Non-tabular content: the source appears to be markup.")
    if _looks_like_json(text):
        raise BadRequest("Non-tabular content: the source appears to be JSON.")
    return infer_and_parse(text)


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------

_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_TIME_RE = re.compile(
    r"""
    \d{1,2}
    :
    \d{1,2}
    (?::\d{1,2}(?:\.\d+)?)?
    (?:\s*[APap]\.?[Mm]\.?)?
    """,
    re.VERBOSE,
)


def _has_leading_zero(token: str) -> bool:
    digits = token.lstrip("+-")
    return len(digits) > 1 and digits[0] == "0"


def coerce(value: str) -> Any:
    """Deterministically coerce a CSV cell into its JSON representation.

    Integers and decimals become JSON numbers; everything else -- including
    time-like values such as `08:30`, `9:15` and `12:00` -- stays text.
    """
    token = value.strip()
    if not token:
        return value.strip()

    # Time-like values are checked first so `12:00` never looks numeric.
    if _TIME_RE.fullmatch(token):
        return token

    if _INT_RE.fullmatch(token):
        if _has_leading_zero(token):
            return token  # preserve zero-padded identifiers verbatim
        try:
            return int(token)
        except ValueError:
            return token

    if _FLOAT_RE.fullmatch(token):
        if _has_leading_zero(token.split(".")[0].split("e")[0].split("E")[0]):
            return token
        try:
            number = float(token)
        except (ValueError, OverflowError):
            return token
        if number != number or number in (float("inf"), float("-inf")):
            return token  # NaN / Infinity are not representable in JSON
        return number

    return token


# --------------------------------------------------------------------------
# Flask application
# --------------------------------------------------------------------------


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        methods=["GET", "HEAD", "OPTIONS"],
        allow_headers="*",
        expose_headers="*",
        max_age=86400,
    )

    def ok(payload: Dict[str, Any], status: int = 200):
        body = {"ok": True}
        body.update(payload)
        return _json_response(body, status)

    def fail(message: str, status: int):
        return _json_response({"ok": False, "error": message}, status)

    def _json_response(body: Dict[str, Any], status: int):
        response = app.response_class(
            response=json.dumps(body, ensure_ascii=False, allow_nan=False) + "\n",
            status=status,
            mimetype="application/json",
        )
        _apply_cors(response)
        return response

    def _apply_cors(response) -> None:
        headers = response.headers
        headers.setdefault("Access-Control-Allow-Origin", "*")
        headers.setdefault(
            "Access-Control-Allow-Methods", "GET, HEAD, OPTIONS"
        )
        headers.setdefault("Access-Control-Allow-Headers", "*")
        headers.setdefault("Access-Control-Expose-Headers", "*")
        headers.setdefault("Access-Control-Max-Age", "86400")

    # -- routes ----------------------------------------------------------

    @app.route("/convert", methods=["GET", "HEAD", "OPTIONS"])
    def convert():
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        try:
            source = validate_source(request.args.get("source"))
            charset = validate_charset(request.args.get("charset"))
            raw = fetch_source(source)
            text = decode_bytes(raw, charset)
            columns, rows = parse_tabular(raw, text)
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        typed = [[coerce(cell) for cell in row] for row in rows]
        rowids = list(range(FIRST_DATA_ROWID, FIRST_DATA_ROWID + len(typed)))
        dataset_id = STORE.make_id(source)
        STORE.put(
            dataset_id,
            {
                "source": source,
                "columns": columns,
                "rows": typed,
                "rowids": rowids,
            },
        )
        return ok({"endpoint": "/datasets/%s" % dataset_id})

    @app.route("/datasets/<dataset_id>", methods=["GET", "HEAD", "OPTIONS"])
    def dataset(dataset_id: str):
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        started = time.perf_counter()
        record = STORE.get(dataset_id)
        if record is None:
            return fail("Unknown dataset id: %r." % dataset_id, 404)

        columns = list(record["columns"])
        try:
            controls = parse_controls(request.args, columns)
        except DataGateError as exc:
            return fail(exc.message, exc.status)

        source_rows: List[List[Any]] = record["rows"]
        rowids: List[int] = record["rowids"]
        total = len(source_rows)

        ordered = list(zip(rowids, source_rows))
        if controls.sort_index is not None:
            index = controls.sort_index
            # `list.sort` is stable in both directions, so ties keep source order.
            ordered.sort(
                key=lambda pair: sort_key(pair[1][index]),
                reverse=controls.sort_desc,
            )
        window = ordered[controls.offset : controls.offset + controls.size]

        rows: List[Any]
        if controls.shape == "objects":
            rows = [
                _as_object(rowid, row, columns, controls.hide_rowid)
                for rowid, row in window
            ]
        else:
            rows = [list(row) for _rowid, row in window]

        payload: Dict[str, Any] = {"columns": columns}
        if not controls.hide_total:
            payload["total"] = total
        payload["rows"] = rows
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        payload["query_ms"] = round(elapsed_ms, 4)
        return ok(payload)

    @app.route("/", methods=["GET", "HEAD", "OPTIONS"])
    def index():
        if request.method == "OPTIONS":
            return _json_response({"ok": True}, 200)
        return ok(
            {
                "service": "datagate",
                "endpoints": [
                    "/convert?source=<url>[&charset=<name>]",
                    "/datasets/<id>[?_size=&_offset=&_sort=&_sort_desc="
                    "&_shape=&_rowid=hide&_total=hide]",
                ],
            }
        )

    # -- error handling --------------------------------------------------

    @app.errorhandler(400)
    def _bad_request(exc):
        return fail(_describe(exc, "Bad request."), 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return fail(_describe(exc, "Not found."), 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return fail(_describe(exc, "Method not allowed."), 405)

    @app.errorhandler(DataGateError)
    def _datagate_error(exc: DataGateError):
        return fail(exc.message, exc.status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, DataGateError):
            return fail(exc.message, exc.status)
        status = getattr(exc, "code", None)
        if isinstance(status, int):
            return fail(_describe(exc, "Request failed."), status)
        app.logger.exception("Unhandled error")
        return fail("Internal server error: %s" % _brief(exc), 500)

    @app.after_request
    def _after(response):
        _apply_cors(response)
        return response

    return app


def _as_object(
    rowid: int, row: List[Any], columns: List[str], hide_rowid: bool
) -> Dict[str, Any]:
    """Render one row as an object, with `rowid` leading unless hidden."""
    obj: Dict[str, Any] = {}
    if not hide_rowid:
        obj["rowid"] = rowid
    for name, value in zip(columns, row):
        obj[name] = value
    return obj


def _describe(exc: Any, default: str) -> str:
    description = getattr(exc, "description", None)
    if isinstance(description, str) and description.strip():
        return description
    return default


# --------------------------------------------------------------------------
# Control parameters
# --------------------------------------------------------------------------

# ASCII digits only: `int()` would happily accept other Unicode digit forms.
_UNSIGNED_INT_RE = re.compile(r"\+?[0-9]+")


class Controls:
    """The validated pagination / sorting / shape controls of one request."""

    __slots__ = (
        "size",
        "offset",
        "shape",
        "sort_index",
        "sort_desc",
        "hide_rowid",
        "hide_total",
    )

    def __init__(
        self,
        size: int = DEFAULT_ROW_LIMIT,
        offset: int = 0,
        shape: str = "lists",
        sort_index: Optional[int] = None,
        sort_desc: bool = False,
        hide_rowid: bool = False,
        hide_total: bool = False,
    ) -> None:
        self.size = size
        self.offset = offset
        self.shape = shape
        self.sort_index = sort_index
        self.sort_desc = sort_desc
        self.hide_rowid = hide_rowid
        self.hide_total = hide_total


def _reject_repeats(args: Any) -> None:
    """A control parameter given more than once is always a client error."""
    for name in CONTROL_PARAMS:
        if len(args.getlist(name)) > 1:
            raise BadRequest(
                "Query parameter '%s' must not be repeated." % name
            )


def _parse_unsigned(name: str, raw: Optional[str], minimum: int, default: int) -> int:
    """Parse a base-10 integer that must be >= `minimum`."""
    if raw is None:
        return default
    token = raw.strip()
    wanted = "a positive integer" if minimum > 0 else "a non-negative integer"
    if not _UNSIGNED_INT_RE.fullmatch(token):
        raise BadRequest(
            "Query parameter '%s' must be %s, got %r." % (name, wanted, raw)
        )
    value = int(token)
    if value < minimum:
        raise BadRequest(
            "Query parameter '%s' must be %s, got %r." % (name, wanted, raw)
        )
    return value


def _parse_shape(raw: Optional[str]) -> str:
    if raw is None:
        return SHAPES[0]
    shape = raw.strip()
    if shape not in SHAPES:
        raise BadRequest(
            "Query parameter '_shape' must be one of %s, got %r."
            % (" or ".join("'%s'" % s for s in SHAPES), raw)
        )
    return shape


def _parse_toggle(name: str, raw: Optional[str]) -> bool:
    """`_rowid` / `_total` accept the single value `hide`."""
    if raw is None:
        return False
    if raw.strip() != HIDE:
        raise BadRequest(
            "Query parameter '%s' only accepts the value '%s', got %r."
            % (name, HIDE, raw)
        )
    return True


def _parse_sort_column(name: str, raw: str, columns: List[str]) -> int:
    column = raw.strip()
    if not column:
        raise BadRequest("Query parameter '%s' must name a column." % name)
    try:
        return columns.index(column)
    except ValueError:
        raise BadRequest(
            "Query parameter '%s' names an unknown column: %r." % (name, raw)
        ) from None


def parse_controls(args: Any, columns: List[str]) -> Controls:
    """Validate every control parameter of a /datasets/<id> request."""
    _reject_repeats(args)

    controls = Controls(
        size=_parse_unsigned("_size", args.get("_size"), 1, DEFAULT_ROW_LIMIT),
        offset=_parse_unsigned("_offset", args.get("_offset"), 0, 0),
        shape=_parse_shape(args.get("_shape")),
        hide_rowid=_parse_toggle("_rowid", args.get("_rowid")),
        hide_total=_parse_toggle("_total", args.get("_total")),
    )

    # Both sort parameters are validated even when only one of them is used,
    # then `_sort_desc` wins whenever the two are given together.
    ascending = args.get("_sort")
    descending = args.get("_sort_desc")
    if ascending is not None:
        controls.sort_index = _parse_sort_column("_sort", ascending, columns)
        controls.sort_desc = False
    if descending is not None:
        controls.sort_index = _parse_sort_column("_sort_desc", descending, columns)
        controls.sort_desc = True
    return controls


def sort_key(value: Any) -> Tuple[int, float, str]:
    """Total order across the mixed JSON types a column may hold.

    Numbers sort together ahead of text so that comparisons never depend on
    types Python refuses to order against each other.
    """
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, str(value))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datagate",
        description="Convert remote CSV files into queryable JSON datasets.",
    )
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start", help="Start the datagate HTTP server.")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", type=str, default=DEFAULT_ADDRESS)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.command != "start":
        parser.print_help()
        return 1

    app = create_app()
    app.run(
        host=args.address,
        port=args.port,
        threaded=True,
        debug=False,
        use_reloader=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

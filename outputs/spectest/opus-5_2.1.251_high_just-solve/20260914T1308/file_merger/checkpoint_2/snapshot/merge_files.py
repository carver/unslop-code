#!/usr/bin/env python3
"""Merge heterogeneous tabular inputs into a single schema-aligned, sorted CSV.

Supported input formats are CSV, TSV, JSON Lines (NDJSON) and Parquet, each
optionally gzip-compressed.  Every input is streamed, reconciled against a
resolved output schema, cast cell by cell, buffered until the memory budget is
reached, spilled to sorted temporary run files and finally k-way merged onto
the output stream.  Peak memory therefore stays bounded regardless of how large
the inputs are.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import json
import os
import re
import shutil
import sys
import zlib
import tempfile
from datetime import date as date_cls
from datetime import datetime
from datetime import time as time_cls
from datetime import timedelta, timezone
from decimal import Decimal

VALID_TYPES = ("string", "int", "float", "bool", "date", "timestamp")

# timestamp > date > bool > int > float > string  (lower number == higher priority)
TYPE_PRIORITY = {
    "timestamp": 0,
    "date": 1,
    "bool": 2,
    "int": 3,
    "float": 4,
    "string": 5,
}

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:[.,](\d{1,9}))?)?"
    r"\s*(Z|z|[+-]\d{2}:?\d{2}|[+-]\d{2})?$"
)

BOOL_TRUE = ("true", "1")
BOOL_FALSE = ("false", "0")

PROG = "merge_files.py"

# Exit codes.
EXIT_OK = 0
EXIT_USAGE = 2  # bad invocation, unreadable input, undetectable format
EXIT_SCHEMA = 3  # schema problems (including unknown --key columns)
EXIT_TYPE = 4  # cast failure under --on-type-error=fail
EXIT_MALFORMED = 5  # malformed input / dialect or compression mismatch
EXIT_UNSUPPORTED = 6  # nested (non-flat) JSONL or Parquet structures

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

EXT_FORMAT = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}

RAW_FORMATS = ("csv", "tsv")
TYPED_FORMATS = ("jsonl", "parquet")

# Precedence used by --schema-strategy=authoritative: typed sources first.
FORMAT_RANK = {"parquet": 0, "jsonl": 1, "csv": 2, "tsv": 2}


class UserError(Exception):
    """Fatal, user-facing error: reported on stderr with a non-zero exit."""

    def __init__(self, message, code=EXIT_USAGE):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# Parsing / casting primitives
# --------------------------------------------------------------------------


def parse_int(text):
    s = text.strip()
    if INT_RE.match(s):
        return int(s)
    return None


def parse_float(text):
    s = text.strip()
    if FLOAT_RE.match(s):
        try:
            return float(s)
        except ValueError:
            return None
    return None


def parse_bool(text):
    s = text.strip().lower()
    if s in BOOL_TRUE:
        return True
    if s in BOOL_FALSE:
        return False
    return None


def parse_date_only(text):
    """Parse a strict ISO-8601 calendar date (YYYY-MM-DD)."""
    m = DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_timestamp(text):
    """Parse an ISO-8601 timestamp, normalized to an aware UTC datetime.

    A naive value (no zone) is treated as UTC; a date-only value is midnight UTC.
    """
    s = text.strip()
    m = TS_RE.match(s)
    if m:
        year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
        second = int(m.group(6) or 0)
        frac = m.group(7) or ""
        micro = int((frac + "000000")[:6]) if frac else 0
        try:
            dt = datetime(year, month, day, hour, minute, second, micro)
        except ValueError:
            return None
        zone = m.group(8)
        if zone and zone not in ("Z", "z"):
            body = zone[1:].replace(":", "")
            hours = int(body[:2])
            minutes = int(body[2:4]) if len(body) > 2 else 0
            if minutes > 59:
                return None
            offset = timedelta(hours=hours, minutes=minutes)
            if zone[0] == "-":
                offset = -offset
            try:
                dt = dt.replace(tzinfo=timezone(offset))
            except ValueError:
                return None
        else:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return parse_date_only(s)


def format_timestamp(dt):
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += "." + ("%06d" % dt.microsecond).rstrip("0")
    return base + "Z"


def cast_cell(typ, text):
    """Cast raw text to ``typ``.

    Returns ``(ok, output_text, sort_key)``. The sort key is a JSON-serializable
    list; ``[1, 0, n]`` ranks numeric-ish values before ``[1, 1, s]`` textual
    ones so heterogeneous columns (``--on-type-error keep-string``) stay
    totally ordered.
    """
    if typ == "string":
        return True, text, [1, 1, text]
    if typ == "int":
        value = parse_int(text)
        if value is None:
            return False, None, None
        return True, str(value), [1, 0, value]
    if typ == "float":
        value = parse_float(text)
        if value is None:
            return False, None, None
        return True, repr(value), [1, 0, value]
    if typ == "bool":
        value = parse_bool(text)
        if value is None:
            return False, None, None
        return True, ("true" if value else "false"), [1, 0, 1 if value else 0]
    if typ == "date":
        dt = parse_timestamp(text)
        if dt is None:
            return False, None, None
        iso = dt.strftime("%Y-%m-%d")
        return True, iso, [1, 1, iso]
    if typ == "timestamp":
        dt = parse_timestamp(text)
        if dt is None:
            return False, None, None
        return True, format_timestamp(dt), [1, 0, dt.timestamp()]
    raise UserError("unknown type %r" % typ, EXIT_SCHEMA)


# --------------------------------------------------------------------------
# Typed (JSONL / Parquet) value handling
# --------------------------------------------------------------------------


def normalize_typed(value):
    """Reduce a JSONL/Parquet value to one of the shapes the caster handles."""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def normalize_json_number(value):
    """JSON numbers prefer ``int`` when integral and inside the int64 range."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if INT64_MIN <= value <= INT64_MAX:
            return value
        return float(value)
    if isinstance(value, float):
        if value.is_integer() and INT64_MIN <= value <= INT64_MAX:
            return int(value)
        return value
    return value


def typed_to_string(value):
    """Canonical string rendering of a typed value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, date_cls):
        return value.isoformat()
    if isinstance(value, time_cls):
        return value.isoformat()
    return str(value)


def cast_value(typ, value):
    """Cast an already-typed JSONL/Parquet value to ``typ``.

    Returns ``(ok, output_text, sort_key)`` exactly like :func:`cast_cell`.
    """
    value = normalize_typed(value)

    if isinstance(value, str):
        # A typed string still has to satisfy the target type's text rules.
        return cast_cell(typ, value)

    if typ == "string":
        text = typed_to_string(value)
        return True, text, [1, 1, text]

    if typ == "int":
        if isinstance(value, bool):
            number = 1 if value else 0
        elif isinstance(value, int):
            number = value
        elif isinstance(value, float):
            if not value.is_integer():
                return False, None, None
            number = int(value)
        else:
            return False, None, None
        return True, str(number), [1, 0, number]

    if typ == "float":
        if isinstance(value, bool):
            number = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            number = float(value)
        else:
            return False, None, None
        return True, repr(number), [1, 0, number]

    if typ == "bool":
        if isinstance(value, bool):
            flag = value
        elif isinstance(value, int) and value in (0, 1):
            flag = bool(value)
        elif isinstance(value, float) and value in (0.0, 1.0):
            flag = bool(value)
        else:
            return False, None, None
        return True, ("true" if flag else "false"), [1, 0, 1 if flag else 0]

    if typ == "date":
        if isinstance(value, datetime):
            iso = value.strftime("%Y-%m-%d")
        elif isinstance(value, date_cls):
            iso = value.isoformat()
        else:
            return False, None, None
        return True, iso, [1, 1, iso]

    if typ == "timestamp":
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date_cls):
            dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        else:
            return False, None, None
        return True, format_timestamp(dt), [1, 0, dt.timestamp()]

    raise UserError("unknown type %r" % typ, EXIT_SCHEMA)


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------


def value_candidates(text):
    """Return ``(candidate_types, has_time)`` for one observed raw value."""
    candidates = {"string"}
    has_time = False
    stripped = text.strip()
    if parse_int(stripped) is not None:
        candidates.add("int")
    if parse_float(stripped) is not None:
        candidates.add("float")
    if parse_bool(stripped) is not None:
        candidates.add("bool")
    if DATE_RE.match(stripped):
        if parse_date_only(stripped) is not None:
            candidates.add("date")
            candidates.add("timestamp")
    elif TS_RE.match(stripped):
        if parse_timestamp(stripped) is not None:
            candidates.add("timestamp")
            has_time = True
    return candidates, has_time


def typed_value_candidates(value):
    """Return ``(candidate_types, has_time)`` for one observed typed value."""
    value = normalize_typed(value)
    if isinstance(value, str):
        return value_candidates(value)
    if isinstance(value, bool):
        return {"bool", "string"}, False
    if isinstance(value, int):
        candidates = {"int", "float", "string"}
        if value in (0, 1):
            candidates.add("bool")
        return candidates, False
    if isinstance(value, float):
        candidates = {"float", "string"}
        if value in (0.0, 1.0):
            candidates.add("bool")
        return candidates, False
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return {"timestamp", "date", "string"}, False
        return {"timestamp", "string"}, True
    if isinstance(value, date_cls):
        return {"date", "timestamp", "string"}, False
    return {"string"}, False


def type_candidates(typ):
    """Which target types can losslessly hold every value of ``typ``."""
    if typ == "int":
        return {"int", "float", "string"}
    if typ == "float":
        return {"float", "string"}
    if typ == "bool":
        return {"bool", "string"}
    if typ == "date":
        return {"date", "timestamp", "string"}
    if typ == "timestamp":
        return {"timestamp", "string"}
    return {"string"}


def widen(left, right):
    """Simplest common type that can hold both ``left`` and ``right``."""
    if left == right:
        return left
    pair = {left, right}
    if pair == {"int", "float"}:
        return "float"
    if pair == {"date", "timestamp"}:
        return "timestamp"
    return "string"


class ColumnObserver:
    """Accumulates the intersection of candidate types over observed values."""

    __slots__ = ("candidates", "has_time", "observed", "declared")

    def __init__(self, declared=None):
        self.candidates = None  # None == nothing observed yet
        self.has_time = False
        self.observed = False
        self.declared = declared
        if declared is not None:
            self.observed = True
            self.candidates = set(type_candidates(declared))
            self.has_time = declared == "timestamp"

    def _merge(self, candidates, has_time):
        self.observed = True
        self.has_time = self.has_time or has_time
        if self.candidates is None:
            self.candidates = set(candidates)
        else:
            self.candidates &= candidates

    def observe(self, text):
        self._merge(*value_candidates(text))

    def observe_typed(self, value):
        self._merge(*typed_value_candidates(value))

    def resolve(self):
        if self.declared is not None:
            return self.declared
        if not self.observed or not self.candidates:
            return "string"
        best = min(self.candidates, key=lambda t: TYPE_PRIORITY[t])
        # Keep pure date columns as dates: only promote to timestamp when a
        # value actually carried a time component.
        if best == "timestamp" and not self.has_time and "date" in self.candidates:
            return "date"
        return best


# --------------------------------------------------------------------------
# Input format / compression detection
# --------------------------------------------------------------------------


class InputSource:
    """One resolved input: path plus the format and compression to use."""

    __slots__ = ("path", "fmt", "compression", "order", "raw", "rank")

    def __init__(self, path, fmt, compression, order):
        self.path = path
        self.fmt = fmt
        self.compression = compression
        self.order = order
        self.raw = fmt in RAW_FORMATS
        self.rank = FORMAT_RANK[fmt]


def read_head(path, size=8):
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc.strerror or exc))


def read_gzip_head(path, size=8):
    try:
        with gzip.open(path, "rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc.strerror or exc))
    except EOFError:
        return b""
    except Exception as exc:  # zlib/gzip decoding failures
        raise UserError(
            "%s: not a valid gzip stream: %s" % (path, exc), EXIT_MALFORMED
        )


def resolve_compression(path, head, forced):
    is_gzip = head[:2] == GZIP_MAGIC
    ext_gzip = path.lower().endswith(".gz")
    if forced == "none":
        if is_gzip:
            raise UserError(
                "%s: --compression=none but the file is gzip-compressed" % path,
                EXIT_MALFORMED,
            )
        return "none"
    if forced == "gzip":
        if not is_gzip:
            raise UserError(
                "%s: --compression=gzip but the file is not gzip-compressed" % path,
                EXIT_MALFORMED,
            )
        return "gzip"
    # auto
    if ext_gzip and not is_gzip:
        raise UserError(
            "%s: .gz suffix but the file is not gzip-compressed" % path, EXIT_MALFORMED
        )
    return "gzip" if is_gzip else "none"


def resolve_format(path, head, compression, forced):
    if forced != "auto":
        return forced
    lowered = path.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    _, ext = os.path.splitext(lowered)
    fmt = EXT_FORMAT.get(ext)
    if fmt is not None:
        return fmt
    magic = read_gzip_head(path) if compression == "gzip" else head
    if magic[:4] == PARQUET_MAGIC:
        return "parquet"
    raise UserError(
        "cannot determine input format for %s (use --input-format)" % path, EXIT_USAGE
    )


def resolve_inputs(paths, input_format, compression):
    sources = []
    for order, path in enumerate(paths):
        if not os.path.isfile(path):
            raise UserError("input file not found: %s" % path)
        head = read_head(path)
        comp = resolve_compression(path, head, compression)
        fmt = resolve_format(path, head, comp, input_format)
        sources.append(InputSource(path, fmt, comp, order))
    return sources


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


def open_text(source):
    try:
        if source.compression == "gzip":
            return gzip.open(source.path, "rt", encoding="utf-8-sig", newline="")
        return open(source.path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (source.path, exc.strerror or exc))


DECODE_ERRORS = (EOFError, UnicodeDecodeError, zlib.error)


def stream_error(source, exc):
    """Translate a low-level streaming failure into a user-facing error."""
    if isinstance(exc, UnicodeDecodeError):
        return UserError(
            "%s: input is not valid UTF-8: %s" % (source.path, exc), EXIT_MALFORMED
        )
    if isinstance(exc, DECODE_ERRORS) or isinstance(exc, gzip.BadGzipFile):
        return UserError(
            "%s: corrupt or truncated %s stream: %s"
            % (source.path, "gzip" if source.compression == "gzip" else "input", exc),
            EXIT_MALFORMED,
        )
    return UserError(
        "cannot read input %s: %s" % (source.path, getattr(exc, "strerror", None) or exc)
    )


def delimited_dialect(source, options):
    if source.fmt == "tsv":
        return {
            "delimiter": "\t",
            "quotechar": '"',
            "quoting": csv.QUOTE_NONE,
            "escapechar": None,
            "doublequote": False,
        }
    return {
        "delimiter": ",",
        "quotechar": options["quotechar"],
        "escapechar": options["escapechar"],
        "doublequote": options["doublequote"],
    }


def iter_delimited(source, options):
    """Yield ``(header_tuple, values, line_number)`` for a CSV/TSV input."""
    handle = open_text(source)
    try:
        reader = csv.reader(handle, **delimited_dialect(source, options))
        try:
            header = next(reader, None)
        except csv.Error as exc:
            raise UserError(
                "%s:1: malformed %s input: %s" % (source.path, source.fmt.upper(), exc),
                EXIT_MALFORMED,
            )
        if header is None:
            return
        header = tuple(header)
        width = len(header)
        line_no = 1
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                raise UserError(
                    "%s:%d: malformed %s input: %s"
                    % (source.path, line_no + 1, source.fmt.upper(), exc),
                    EXIT_MALFORMED,
                )
            line_no += 1
            if not row:
                continue
            if source.fmt == "tsv" and len(row) > width:
                raise UserError(
                    "%s:%d: literal tab inside a TSV field (%d fields, header has %d)"
                    % (source.path, line_no, len(row), width),
                    EXIT_MALFORMED,
                )
            yield header, row, line_no
    except DECODE_ERRORS as exc:
        raise stream_error(source, exc)
    except OSError as exc:
        raise stream_error(source, exc)
    finally:
        handle.close()


def iter_jsonl(source):
    """Yield ``(keys_tuple, values, line_number)`` for a JSON Lines input."""
    handle = open_text(source)
    shapes = {}
    try:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise UserError(
                    "%s:%d: invalid JSON: %s" % (source.path, line_no, exc),
                    EXIT_MALFORMED,
                )
            if not isinstance(record, dict):
                raise UserError(
                    "%s:%d: JSONL record must be a flat JSON object" % (source.path, line_no),
                    EXIT_UNSUPPORTED,
                )
            keys = tuple(record)
            shape = shapes.get(keys)
            if shape is None:
                shape = keys
                if len(shapes) < 4096:
                    shapes[keys] = keys
            values = []
            for key in keys:
                value = record[key]
                if isinstance(value, (dict, list)):
                    raise UserError(
                        "%s:%d: nested value for field %r is not supported"
                        % (source.path, line_no, key),
                        EXIT_UNSUPPORTED,
                    )
                values.append(normalize_json_number(value))
            yield shape, values, line_no
    except DECODE_ERRORS as exc:
        raise stream_error(source, exc)
    except OSError as exc:
        raise stream_error(source, exc)
    finally:
        handle.close()


def load_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise UserError("reading Parquet inputs requires the 'pyarrow' package (%s)" % exc)
    return pa, pq


def arrow_type_name(pa, arrow_type):
    if pa.types.is_boolean(arrow_type):
        return "bool"
    if pa.types.is_integer(arrow_type):
        return "int"
    if pa.types.is_floating(arrow_type) or pa.types.is_decimal(arrow_type):
        return "float"
    if pa.types.is_date(arrow_type):
        return "date"
    if pa.types.is_timestamp(arrow_type):
        return "timestamp"
    return "string"


def materialize_parquet(source, temp_dir):
    """Parquet needs a seekable file; transparently decompress a .gz input."""
    if source.compression != "gzip":
        return source.path, None
    fd, path = tempfile.mkstemp(prefix="merge_parquet_", suffix=".parquet", dir=temp_dir)
    try:
        with os.fdopen(fd, "wb") as out, gzip.open(source.path, "rb") as src:
            shutil.copyfileobj(src, out, 1024 * 1024)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (source.path, exc.strerror or exc))
    except Exception as exc:
        raise UserError("%s: not a valid gzip stream: %s" % (source.path, exc), EXIT_MALFORMED)
    return path, path


def open_parquet(source, temp_dir):
    """Open a Parquet file and return ``(pa, handle, names, types, scratch)``."""
    pa, pq = load_pyarrow()
    path, scratch = materialize_parquet(source, temp_dir)
    try:
        handle = pq.ParquetFile(path)
    except Exception as exc:
        if scratch:
            _unlink(scratch)
        raise UserError("%s: cannot read Parquet file: %s" % (source.path, exc), EXIT_MALFORMED)
    names, types = [], []
    try:
        for field in handle.schema_arrow:
            if pa.types.is_nested(field.type):
                raise UserError(
                    "%s: nested Parquet field %r (%s) is not supported"
                    % (source.path, field.name, field.type),
                    EXIT_UNSUPPORTED,
                )
            names.append(field.name)
            types.append(arrow_type_name(pa, field.type))
    except UserError:
        handle.close()
        if scratch:
            _unlink(scratch)
        raise
    return pa, handle, names, types, scratch


def parquet_batch_rows(handle, target_bytes):
    """Translate an advisory byte budget into a row-batch size."""
    try:
        meta = handle.metadata
        total_bytes = 0
        total_rows = 0
        for index in range(meta.num_row_groups):
            group = meta.row_group(index)
            total_bytes += group.total_byte_size
            total_rows += group.num_rows
    except Exception:
        total_bytes = total_rows = 0
    if total_rows <= 0 or total_bytes <= 0:
        return 4096
    average = max(1.0, float(total_bytes) / float(total_rows))
    rows = int(target_bytes / average)
    return max(64, min(rows, 131072))


def iter_parquet(source, temp_dir, target_bytes):
    """Yield ``(names_tuple, values, row_number)`` streaming row group-wise."""
    _pa, handle, names, _types, scratch = open_parquet(source, temp_dir)
    names_tuple = tuple(names)
    batch_rows = parquet_batch_rows(handle, target_bytes)
    row_no = 0
    try:
        if not names:
            return
        for batch in handle.iter_batches(batch_size=batch_rows):
            columns = [column.to_pylist() for column in batch.columns]
            for values in zip(*columns):
                row_no += 1
                yield names_tuple, list(values), row_no
    except UserError:
        raise
    except Exception as exc:
        raise UserError("%s: cannot read Parquet file: %s" % (source.path, exc), EXIT_MALFORMED)
    finally:
        try:
            handle.close()
        except Exception:
            pass
        if scratch:
            _unlink(scratch)


def iter_source(source, options):
    if source.fmt in RAW_FORMATS:
        return iter_delimited(source, options)
    if source.fmt == "jsonl":
        return iter_jsonl(source)
    if source.fmt == "parquet":
        return iter_parquet(source, options["temp_dir"], options["parquet_bytes"])
    raise UserError("unsupported input format %r" % source.fmt)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------


def load_schema(spec):
    text = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as handle:
                text = handle.read()
        except OSError as exc:
            raise UserError("cannot read schema %s: %s" % (spec, exc.strerror or exc))
    else:
        stripped = spec.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            text = stripped
        else:
            raise UserError("schema file not found: %s" % spec)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise UserError("invalid schema JSON: %s" % exc, EXIT_SCHEMA)

    columns = data.get("columns") if isinstance(data, dict) else data
    if not isinstance(columns, list) or not columns:
        raise UserError("schema must contain a non-empty 'columns' list", EXIT_SCHEMA)

    names, types = [], []
    for entry in columns:
        if isinstance(entry, str):
            name, typ = entry, "string"
        elif isinstance(entry, dict):
            name = entry.get("name")
            typ = entry.get("type", "string")
        else:
            raise UserError("invalid schema column entry: %r" % (entry,), EXIT_SCHEMA)
        if not isinstance(name, str) or not name:
            raise UserError("schema column is missing a name", EXIT_SCHEMA)
        if typ not in VALID_TYPES:
            raise UserError(
                "invalid type %r for column %r (valid: %s)" % (typ, name, ", ".join(VALID_TYPES)),
                EXIT_SCHEMA,
            )
        if name in names:
            raise UserError("duplicate column %r in schema" % name, EXIT_SCHEMA)
        names.append(name)
        types.append(typ)
    return names, types


class FileStats:
    """Per-input column observations used for schema reconciliation."""

    __slots__ = ("source", "observers")

    def __init__(self, source, observers):
        self.source = source
        self.observers = observers


def observe_source(source, options):
    """Collect one :class:`ColumnObserver` per column of a single input."""
    observers = {}
    mode = options["infer"]
    null_literal = options["null_literal"]
    loose = mode == "loose"

    if source.fmt == "parquet":
        _pa, handle, names, types, scratch = open_parquet(source, options["temp_dir"])
        try:
            for name, typ in zip(names, types):
                if name not in observers:
                    observers[name] = ColumnObserver(declared=typ)
        finally:
            try:
                handle.close()
            except Exception:
                pass
            if scratch:
                _unlink(scratch)
        return observers

    raw = source.raw
    cached_names = None
    slots = None
    for names, values, _line_no in iter_source(source, options):
        if names is not cached_names:
            cached_names = names
            slots = []
            seen = set()
            for position, name in enumerate(names):
                if name in seen:
                    continue
                seen.add(name)
                observer = observers.get(name)
                if observer is None:
                    observer = ColumnObserver()
                    observers[name] = observer
                slots.append((position, observer))
        width = len(values)
        for position, observer in slots:
            value = values[position] if position < width else ("" if raw else None)
            if raw:
                if null_literal != "" and value == null_literal:
                    continue
                if loose and value == "":
                    continue
                observer.observe(value)
            else:
                if value is None:
                    continue
                if isinstance(value, str):
                    if null_literal != "" and value == null_literal:
                        continue
                    if loose and value == "":
                        continue
                    observer.observe(value)
                else:
                    observer.observe_typed(value)
    return observers


def resolve_column_type(entries, strategy, mode):
    """Reconcile one column's type across the inputs that carry it."""
    entries = [entry for entry in entries if entry[1].observed]
    if not entries:
        return "string"

    if strategy == "authoritative":
        typed = [e for e in entries if e[0].fmt in TYPED_FORMATS]
        if typed:
            best = min(typed, key=lambda e: (e[0].rank, e[0].order))
            return best[1].resolve()
        if mode == "loose":
            pooled = ColumnObserver()
            for _source, observer in entries:
                pooled._merge(observer.candidates or {"string"}, observer.has_time)
            return pooled.resolve()
        resolved = None
        for _source, observer in entries:
            candidate = observer.resolve()
            if resolved is None:
                resolved = candidate
            elif resolved != candidate:
                return "string"
        return resolved or "string"

    if strategy == "consensus":
        votes = {}
        for _source, observer in entries:
            typ = observer.resolve()
            votes[typ] = votes.get(typ, 0) + 1
        top = max(votes.values())
        tied = sorted((t for t, n in votes.items() if n == top), key=lambda t: TYPE_PRIORITY[t])
        resolved = tied[0]
        for typ in tied[1:]:
            resolved = widen(resolved, typ)
        return resolved

    # union: simplest common type that can hold every observed value.
    candidates = None
    has_time = False
    for _source, observer in entries:
        observed = observer.candidates or {"string"}
        has_time = has_time or observer.has_time
        candidates = set(observed) if candidates is None else (candidates & observed)
    if not candidates:
        return "string"
    best = min(candidates, key=lambda t: TYPE_PRIORITY[t])
    if best == "timestamp" and not has_time and "date" in candidates:
        return "date"
    return best


def infer_schema(sources, options):
    """Infer the output columns (lexicographic) and their reconciled types."""
    per_column = {}
    for source in sources:
        observers = observe_source(source, options)
        for name, observer in observers.items():
            per_column.setdefault(name, []).append((source, observer))

    names = sorted(per_column)
    strategy = options["strategy"]
    mode = options["infer"]
    types = [resolve_column_type(per_column[name], strategy, mode) for name in names]
    return names, types


def is_null_text(text, null_literal, treat_empty_as_null=True):
    if text == "" and treat_empty_as_null:
        return True
    if null_literal != "" and text == null_literal:
        return True
    return False


# --------------------------------------------------------------------------
# External sort
# --------------------------------------------------------------------------


class RunWriter:
    """Buffers records, spilling sorted runs to disk when the budget is hit."""

    def __init__(self, temp_dir, budget_bytes, reverse):
        self.temp_dir = temp_dir
        self.budget_bytes = max(budget_bytes, 256 * 1024)
        self.reverse = reverse
        self.buffer = []
        self.buffer_bytes = 0
        self.runs = []

    def add(self, record, approx_bytes):
        self.buffer.append(record)
        self.buffer_bytes += approx_bytes
        if self.buffer_bytes >= self.budget_bytes:
            self.spill()

    def spill(self):
        if not self.buffer:
            return
        self.buffer.sort(reverse=self.reverse)
        fd, path = tempfile.mkstemp(prefix="merge_run_", suffix=".jsonl", dir=self.temp_dir)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            for record in self.buffer:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
        self.runs.append(path)
        self.buffer = []
        self.buffer_bytes = 0

    def sorted_records(self):
        """Yield every record in final sorted order."""
        if not self.runs:
            self.buffer.sort(reverse=self.reverse)
            return iter(self.buffer)
        self.spill()
        streams = [read_run(path) for path in self.runs]
        return heapq.merge(*streams, reverse=self.reverse)

    def cleanup(self):
        for path in self.runs:
            _unlink(path)
        self.runs = []
        self.buffer = []


def read_run(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for line in handle:
            if line:
                yield json.loads(line)


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------


def single_char(value):
    if len(value) != 1:
        raise argparse.ArgumentTypeError("expected a single character, got %r" % value)
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument(
        "--key",
        required=True,
        action="append",
        help="sort key column(s); comma-separated, may be repeated",
    )
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument("--schema", help="schema JSON file (or inline JSON)")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict")
    parser.add_argument(
        "--schema-strategy",
        choices=("authoritative", "consensus", "union"),
        default="authoritative",
    )
    parser.add_argument(
        "--on-type-error",
        choices=("coerce-null", "fail", "keep-string"),
        default="coerce-null",
    )
    parser.add_argument("--memory-limit-mb", type=int, default=64)
    parser.add_argument("--temp-dir", help="directory for intermediate run files")
    parser.add_argument("--csv-quotechar", type=single_char, default='"')
    parser.add_argument("--csv-escapechar", type=single_char, default=None)
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument(
        "--input-format",
        choices=("auto", "csv", "tsv", "jsonl", "parquet"),
        default="auto",
    )
    parser.add_argument("--compression", choices=("auto", "none", "gzip"), default="auto")
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=0,
        help="advisory batch size in bytes when streaming Parquet row groups",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def run(args):
    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise UserError("--memory-limit-mb must be a positive integer")
    if args.parquet_row_group_bytes is not None and args.parquet_row_group_bytes < 0:
        raise UserError("--parquet-row-group-bytes must be a non-negative integer")

    keys = []
    for chunk in args.key:
        for name in chunk.split(","):
            name = name.strip()
            if name and name not in keys:
                keys.append(name)
    if not keys:
        raise UserError("--key requires at least one column name")

    sources = resolve_inputs(args.inputs, args.input_format, args.compression)

    memory_bytes = args.memory_limit_mb * 1024 * 1024
    parquet_bytes = args.parquet_row_group_bytes or max(1024 * 1024, memory_bytes // 8)

    temp_dir = args.temp_dir
    owns_temp_dir = False
    if temp_dir:
        try:
            os.makedirs(temp_dir, exist_ok=True)
        except OSError as exc:
            raise UserError("cannot use --temp-dir %s: %s" % (temp_dir, exc.strerror or exc))
    else:
        temp_dir = tempfile.mkdtemp(prefix="merge_files_")
        owns_temp_dir = True

    options = {
        "quotechar": args.csv_quotechar,
        "escapechar": args.csv_escapechar,
        "doublequote": args.csv_escapechar is None,
        "null_literal": args.csv_null_literal,
        "infer": args.infer,
        "strategy": args.schema_strategy,
        "temp_dir": temp_dir,
        "parquet_bytes": parquet_bytes,
    }
    null_literal = args.csv_null_literal

    writer = None
    try:
        if args.schema:
            names, types = load_schema(args.schema)
        else:
            names, types = infer_schema(sources, options)

        if not names:
            raise UserError("no columns found in the inputs", EXIT_SCHEMA)

        missing = [k for k in keys if k not in names]
        if missing:
            raise UserError(
                "key column%s not present in resolved schema: %s"
                % ("" if len(missing) == 1 else "s", ", ".join(missing)),
                EXIT_SCHEMA,
            )

        key_positions = [names.index(k) for k in keys]
        key_position_set = set(key_positions)
        on_type_error = args.on_type_error
        reverse = bool(args.desc)

        # Serialized records cost far less than the equivalent live Python
        # objects, so only part of the budget is handed to the sort buffer.
        writer = RunWriter(temp_dir, int(memory_bytes * 0.25), reverse)

        sequence = 0
        for source in sources:
            raw = source.raw
            cached_names = None
            projection = None
            for row_names, values, line_no in iter_source(source, options):
                if row_names is not cached_names:
                    cached_names = row_names
                    index = {}
                    for position, name in enumerate(row_names):
                        if name not in index:
                            index[name] = position
                    projection = [index.get(name) for name in names]

                width = len(values)
                out_values = []
                cell_keys = {}
                for column_position, typ in enumerate(types):
                    position = projection[column_position]
                    if position is None or position >= width:
                        out_values.append(None)
                        if column_position in key_position_set:
                            cell_keys[column_position] = None
                        continue
                    cell = values[position]

                    if raw:
                        if is_null_text(cell, null_literal):
                            out_values.append(None)
                            if column_position in key_position_set:
                                cell_keys[column_position] = None
                            continue
                        ok, out, cell_key = cast_cell(typ, cell)
                        original = cell
                    else:
                        if cell is None or (
                            null_literal != ""
                            and isinstance(cell, str)
                            and cell == null_literal
                        ):
                            out_values.append(None)
                            if column_position in key_position_set:
                                cell_keys[column_position] = None
                            continue
                        ok, out, cell_key = cast_value(typ, cell)
                        original = typed_to_string(normalize_typed(cell))

                    if not ok:
                        if on_type_error == "fail":
                            raise UserError(
                                "%s:%d: cannot cast %r to %s for column %r"
                                % (source.path, line_no, original, typ, names[column_position]),
                                EXIT_TYPE,
                            )
                        if on_type_error == "keep-string":
                            out, cell_key = original, [1, 1, original]
                        else:  # coerce-null
                            out, cell_key = None, None
                    out_values.append(out)
                    if column_position in key_position_set:
                        cell_keys[column_position] = cell_key

                # Key order follows --key; nulls sort before non-nulls in
                # either direction (so they land last when reversed).
                ordered_key = [cell_keys.get(position) or [0] for position in key_positions]

                sequence += 1
                tiebreak = -sequence if reverse else sequence
                record = [ordered_key, tiebreak, out_values]
                approx = 96 + sum(len(v) + 48 for v in out_values if v is not None)
                writer.add(record, approx)

        write_output(args.output, names, writer.sorted_records(), null_literal, options)
    finally:
        if writer is not None:
            writer.cleanup()
        if owns_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return EXIT_OK


def write_output(destination, names, records, null_literal, options):
    out_dialect = {
        "delimiter": ",",
        "quotechar": options["quotechar"],
        "escapechar": options["escapechar"],
        "doublequote": options["doublequote"],
        "lineterminator": "\n",
        "quoting": csv.QUOTE_MINIMAL,
    }

    def emit(handle):
        out = csv.writer(handle, **out_dialect)
        out.writerow(names)
        for record in records:
            out.writerow([null_literal if v is None else v for v in record[2]])
        handle.flush()

    if destination == "-":
        handle = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="", closefd=False)
        try:
            emit(handle)
        finally:
            try:
                handle.flush()
            except Exception:
                pass
        return

    target = os.path.abspath(destination)
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise UserError("cannot create output directory: %s" % (exc.strerror or exc))
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".merge_files_", suffix=".tmp", dir=parent or ".")
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            emit(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        _unlink(tmp_path)
        raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))
    except BaseException:
        _unlink(tmp_path)
        raise


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except UserError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return exc.code
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:
            pass
        return EXIT_OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

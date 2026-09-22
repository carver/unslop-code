#!/usr/bin/env python3
"""Merge heterogeneous tabular inputs into one schema-aligned, sorted CSV.

Supported inputs are CSV, TSV, JSON Lines (NDJSON) and Parquet, optionally
gzip compressed.  All inputs are reconciled onto a single output schema (either
given with ``--schema`` or inferred across every input), every cell is cast to
the resolved column type and the result is written as one CSV sorted by the
composite ``--key``.

Sorting uses an external merge sort and every reader streams its input, so
inputs far larger than ``--memory-limit-mb`` can be processed.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import gzip
import heapq
import io
import json
import math
import os
import pickle
import re
import shutil
import signal
import sys
import tempfile
from collections import Counter
from datetime import date as date_cls, datetime, timedelta, timezone
from decimal import Decimal

PROG = "merge_files.py"

VALID_TYPES = ("string", "int", "float", "bool", "date", "timestamp")
# Highest priority first: timestamp > date > bool > int > float > string
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Sort-value ranks. Nulls sort before everything, numbers before strings.
RANK_NULL = -1
RANK_NUM = 0
RANK_STR = 1
NULL_SORT = (RANK_NULL,)

# Maximum number of run files merged in a single pass (keeps fd usage bounded).
MERGE_FANOUT = 32

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

FORMATS = ("csv", "tsv", "jsonl", "parquet")

EXTENSION_FORMATS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}

# Schema precedence for --schema-strategy=authoritative (lower wins).
# Typed sources first; JSONL ranks equal to CSV.
FORMAT_RANK = {"parquet": 0, "jsonl": 1, "csv": 1, "tsv": 2}

MISSING = object()   # a cell that is absent or null


# --------------------------------------------------------------------------
# Errors and exit codes
# --------------------------------------------------------------------------

class MergeError(Exception):
    """Fatal, user facing error."""

    code = 1


class UsageError(MergeError):
    """Bad invocation: unusable argument, unreadable or undetectable input."""

    code = 2


class SchemaError(MergeError):
    """The resolved schema is unusable (bad schema document, missing key)."""

    code = 3


class TypeError_(MergeError):
    """A value could not be cast and --on-type-error=fail was requested."""

    code = 4


class InputError(MergeError):
    """Malformed input data (dialect violation, compression mismatch)."""

    code = 5


class UnsupportedError(MergeError):
    """The input uses a structure this tool does not support (nesting)."""

    code = 6


class CastError(Exception):
    """A cell could not be cast into the requested type."""


# --------------------------------------------------------------------------
# Parsing / casting primitives
# --------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
_TS_RE = re.compile(
    r"^([0-9]{4})-([0-9]{2})-([0-9]{2})"          # date
    r"[Tt ]"                                       # separator
    r"([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?"       # time (seconds optional)
    r"(\.[0-9]+)?"                                 # fractional seconds
    r"(Z|z|[+-][0-9]{2}:?[0-9]{2}(?::?[0-9]{2})?)?$"  # zone
)

_TRUE_LITERALS = frozenset(("true", "1"))
_FALSE_LITERALS = frozenset(("false", "0"))


def parse_int(raw: str) -> int:
    text = raw.strip()
    if not _INT_RE.match(text):
        raise CastError(raw)
    return int(text)


def parse_float(raw: str) -> float:
    text = raw.strip()
    if not text:
        raise CastError(raw)
    try:
        value = float(text)
    except ValueError:
        raise CastError(raw) from None
    if not math.isfinite(value):
        raise CastError(raw)
    return value


def parse_bool(raw: str) -> bool:
    text = raw.strip().lower()
    if text in _TRUE_LITERALS:
        return True
    if text in _FALSE_LITERALS:
        return False
    raise CastError(raw)


def parse_date(raw: str) -> date_cls:
    text = raw.strip()
    m = _DATE_RE.match(text)
    if not m:
        raise CastError(raw)
    year, month, day = (int(g) for g in m.groups())
    try:
        return date_cls(year, month, day)
    except ValueError:
        raise CastError(raw) from None


def parse_timestamp(raw: str, allow_date_only: bool = True):
    """Return (utc_datetime, fractional_seconds_text).

    ``fractional_seconds_text`` keeps the digits exactly as written (including
    the leading dot) or is an empty string when the source had none.
    """
    text = raw.strip()
    m = _TS_RE.match(text)
    if m is None:
        if allow_date_only:
            day = parse_date(text)  # raises CastError when not a plain date
            return datetime(day.year, day.month, day.day, tzinfo=timezone.utc), ""
        raise CastError(raw)

    year, month, dayv, hour, minute, second, frac, zone = m.groups()
    second = second or "00"
    frac = frac or ""

    if zone is None or zone in ("Z", "z"):
        tz = timezone.utc
    else:
        sign = 1 if zone[0] == "+" else -1
        body = zone[1:].replace(":", "")
        if len(body) == 4:
            off_h, off_m, off_s = int(body[0:2]), int(body[2:4]), 0
        else:  # 6 digits: HHMMSS
            off_h, off_m, off_s = int(body[0:2]), int(body[2:4]), int(body[4:6])
        if off_m > 59 or off_s > 59 or off_h > 23:
            raise CastError(raw)
        tz = timezone(sign * timedelta(hours=off_h, minutes=off_m, seconds=off_s))

    micro = 0
    if frac:
        digits = frac[1:]
        micro = int((digits + "000000")[:6])

    try:
        moment = datetime(
            int(year), int(month), int(dayv), int(hour), int(minute), int(second),
            micro, tzinfo=tz,
        )
    except ValueError:
        raise CastError(raw) from None
    return moment.astimezone(timezone.utc), frac


def format_timestamp(moment: datetime, frac: str) -> str:
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
        f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}{frac}Z"
    )


def format_float(value: float) -> str:
    return repr(value)


def timestamp_sort_value(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(microseconds=1)


def _datetime_to_utc(moment: datetime):
    """Normalise a (possibly naive) datetime to UTC plus fractional digits."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    frac = f".{moment.microsecond:06d}" if moment.microsecond else ""
    return moment, frac


def cast_cell(raw: str, type_name: str):
    """Cast the string ``raw`` to ``type_name``; return (sort_value, text)."""
    if type_name == "string":
        return (RANK_STR, raw), raw
    if type_name == "int":
        value = parse_int(raw)
        return (RANK_NUM, value), str(value)
    if type_name == "float":
        value = parse_float(raw)
        return (RANK_NUM, value), format_float(value)
    if type_name == "bool":
        value = parse_bool(raw)
        return (RANK_NUM, 1 if value else 0), ("true" if value else "false")
    if type_name == "date":
        value = parse_date(raw)
        return (RANK_NUM, value.toordinal()), value.isoformat()
    if type_name == "timestamp":
        moment, frac = parse_timestamp(raw, allow_date_only=True)
        return (RANK_NUM, timestamp_sort_value(moment)), format_timestamp(moment, frac)
    raise MergeError(f"unknown type: {type_name}")


def _cast_bool_value(value: bool, type_name: str):
    # A boolean renders as `true`/`false`; just like the CSV spelling of the
    # same value it does not cast into a number.
    if type_name == "bool":
        return (RANK_NUM, 1 if value else 0), ("true" if value else "false")
    if type_name == "string":
        text = "true" if value else "false"
        return (RANK_STR, text), text
    raise CastError(value)


def _cast_int_value(value: int, type_name: str):
    if type_name == "int":
        return (RANK_NUM, value), str(value)
    if type_name == "float":
        number = float(value)
        if not math.isfinite(number):
            raise CastError(value)
        return (RANK_NUM, number), format_float(number)
    if type_name == "bool":
        if value in (0, 1):
            return _cast_bool_value(bool(value), "bool")
        raise CastError(value)
    if type_name == "string":
        text = str(value)
        return (RANK_STR, text), text
    raise CastError(value)


def _cast_float_value(value: float, type_name: str):
    if not math.isfinite(value):
        raise CastError(value)
    if type_name == "float":
        return (RANK_NUM, value), format_float(value)
    if type_name == "int":
        if value.is_integer():
            number = int(value)
            return (RANK_NUM, number), str(number)
        raise CastError(value)
    if type_name == "string":
        text = format_float(value)
        return (RANK_STR, text), text
    raise CastError(value)


def _cast_datetime_value(value: datetime, type_name: str):
    moment, frac = _datetime_to_utc(value)
    if type_name == "timestamp":
        return (RANK_NUM, timestamp_sort_value(moment)), format_timestamp(moment, frac)
    if type_name == "string":
        text = format_timestamp(moment, frac)
        return (RANK_STR, text), text
    raise CastError(value)


def _cast_date_value(value: date_cls, type_name: str):
    if type_name == "date":
        return (RANK_NUM, value.toordinal()), value.isoformat()
    if type_name == "timestamp":
        moment = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return (RANK_NUM, timestamp_sort_value(moment)), format_timestamp(moment, "")
    if type_name == "string":
        text = value.isoformat()
        return (RANK_STR, text), text
    raise CastError(value)


def cast_any(value, type_name: str):
    """Cast a raw string or an already typed value to ``type_name``."""
    if isinstance(value, str):
        return cast_cell(value, type_name)
    if isinstance(value, bool):
        return _cast_bool_value(value, type_name)
    if isinstance(value, int):
        return _cast_int_value(value, type_name)
    if isinstance(value, float):
        return _cast_float_value(value, type_name)
    if isinstance(value, Decimal):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise CastError(value) from None
        return _cast_float_value(number, type_name)
    if isinstance(value, datetime):
        return _cast_datetime_value(value, type_name)
    if isinstance(value, date_cls):
        return _cast_date_value(value, type_name)
    if isinstance(value, (bytes, bytearray)):
        return cast_cell(bytes(value).decode("utf-8", "replace"), type_name)
    return cast_cell(value_text(value), type_name)


def value_text(value) -> str:
    """Canonical string form of a typed value (inference and keep-string)."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_float(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        moment, frac = _datetime_to_utc(value)
        return format_timestamp(moment, frac)
    if isinstance(value, date_cls):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def normalize_number(value):
    """JSON numbers: prefer int when integral and within range, else float."""
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


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------

def _matches(value: str, type_name: str) -> bool:
    try:
        if type_name == "int":
            parse_int(value)
        elif type_name == "float":
            parse_float(value)
        elif type_name == "bool":
            parse_bool(value)
        elif type_name == "date":
            parse_date(value)
        elif type_name == "timestamp":
            # Date-only values must resolve to `date`, never `timestamp`.
            parse_timestamp(value, allow_date_only=False)
        else:
            return True
    except CastError:
        return False
    return True


_CANDIDATE_TYPES = tuple(t for t in TYPE_PRIORITY if t != "string")

# Candidate set implied by a declared (typed source) column type.
DECLARED_CANDIDATES = {
    "string": frozenset(),
    "int": frozenset(("int", "float")),
    "float": frozenset(("float",)),
    "bool": frozenset(("bool",)),
    "date": frozenset(("date",)),
    "timestamp": frozenset(("timestamp",)),
}


def _resolve_candidates(candidates) -> str:
    for type_name in TYPE_PRIORITY:
        if type_name == "string":
            return "string"
        if type_name in candidates:
            return type_name
    return "string"


class ColumnObserver:
    """Tracks which types remain possible for the values seen in one column."""

    __slots__ = ("candidates", "seen")

    def __init__(self, candidates=None, seen=False):
        self.candidates = set(_CANDIDATE_TYPES) if candidates is None else set(candidates)
        self.seen = seen

    def observe(self, value: str) -> None:
        self.seen = True
        if not self.candidates:
            return
        dead = [t for t in self.candidates if not _matches(value, t)]
        if dead:
            self.candidates.difference_update(dead)

    def resolve(self) -> str:
        return _resolve_candidates(self.candidates)


def _combine_candidates(candidate_sets) -> str:
    """Simplest common type able to hold every observed value."""
    sets = list(candidate_sets)
    if not sets:
        return "string"
    common = set(sets[0])
    for other in sets[1:]:
        common &= other
    if common:
        return _resolve_candidates(common)
    # `date` values also fit into a `timestamp` column.
    union = set()
    for other in sets:
        union |= other
    if union and union <= {"date", "timestamp"}:
        return "timestamp"
    return "string"


def _resolve_group(entries, infer_mode: str) -> str:
    """Resolve one group of per-file observations into a single type."""
    if not entries:
        return "string"
    if infer_mode == "loose":
        return _combine_candidates(entry[1] for entry in entries)
    types = {_resolve_candidates(entry[1]) for entry in entries}
    if len(types) == 1:
        return types.pop()
    return "string"   # files disagree


def resolve_column_type(entries, strategy: str, infer_mode: str) -> str:
    """Pick the output type for one column.

    ``entries`` is a list of ``(rank, candidate_set)`` pairs, one per input
    file that observed at least one non-null value for the column.
    """
    if not entries:
        return "string"
    if strategy == "union":
        return _combine_candidates(entry[1] for entry in entries)
    if strategy == "consensus":
        votes = Counter(_resolve_candidates(entry[1]) for entry in entries)
        best = max(votes.values())
        tied = [name for name, count in votes.items() if count == best]
        if len(tied) == 1:
            return tied[0]
        # Tie: fall back to the simplest type that holds every tied type.
        return _combine_candidates(DECLARED_CANDIDATES[name] for name in tied)
    # authoritative (default): the most authoritative sources decide.
    best_rank = min(entry[0] for entry in entries)
    group = [entry for entry in entries if entry[0] == best_rank]
    return _resolve_group(group, infer_mode)


# --------------------------------------------------------------------------
# Input detection: compression and format
# --------------------------------------------------------------------------

def _read_head(path: str, size: int = 8) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise UsageError(f"cannot read input file {path!r}: {exc}") from None


def resolve_compression(path: str, requested: str) -> str:
    """Return 'gzip' or 'none'; a mismatch with the actual bytes is fatal."""
    head = _read_head(path, 2)
    looks_gzip = head[:2] == GZIP_MAGIC
    if requested == "auto":
        chosen = "gzip" if path.lower().endswith(".gz") else "none"
    else:
        chosen = requested
    if chosen == "gzip" and not looks_gzip:
        raise InputError(f"{path}: gzip compression expected but data is not gzip")
    if chosen == "none" and looks_gzip:
        raise InputError(f"{path}: data is gzip compressed but compression is 'none'")
    return chosen


def _decompressed_head(path: str, compression: str, size: int = 8) -> bytes:
    try:
        if compression == "gzip":
            with gzip.open(path, "rb") as handle:
                return handle.read(size)
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise InputError(f"{path}: cannot read input: {exc}") from None
    except (EOFError, gzip.BadGzipFile) as exc:
        raise InputError(f"{path}: corrupt gzip stream: {exc}") from None


def resolve_format(path: str, compression: str, requested: str) -> str:
    """Determine the input format from the flag, the extension or magic bytes."""
    if requested != "auto":
        return requested
    base = path
    if base.lower().endswith(".gz"):
        base = base[:-3]
    extension = os.path.splitext(base)[1].lower()
    fmt = EXTENSION_FORMATS.get(extension)
    if fmt is not None:
        return fmt
    if _decompressed_head(path, compression, 4) == PARQUET_MAGIC:
        return "parquet"
    raise UsageError(
        f"{path}: cannot determine input format from extension or content; "
        f"use --input-format"
    )


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------

def _open_binary(path: str, compression: str):
    try:
        if compression == "gzip":
            return gzip.open(path, "rb")
        return open(path, "rb", buffering=1 << 16)
    except OSError as exc:
        raise UsageError(f"cannot read input file {path!r}: {exc}") from None


def _open_text(path: str, compression: str):
    binary = _open_binary(path, compression)
    return io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")


class Source:
    """One input file: schema scanning and streaming row iteration."""

    fmt = "csv"

    def __init__(self, path: str, compression: str, args):
        self.path = path
        self.compression = compression
        self.args = args
        self.rank = FORMAT_RANK[self.fmt]

    # -- schema pass -------------------------------------------------------
    def scan(self):
        """Return (names, observers): every column name seen and its types."""
        raise NotImplementedError

    # -- data pass ---------------------------------------------------------
    def iter_rows(self, columns):
        """Yield (location, values) with one value per requested column."""
        raise NotImplementedError

    def _wrap_os_error(self, exc):
        return InputError(f"{self.path}: {exc}")


def column_positions(header):
    """Map each column name to its first position in the header."""
    positions = {}
    for index, name in enumerate(header):
        positions.setdefault(name, index)
    return positions


class DelimitedSource(Source):
    """Shared behaviour of the CSV and TSV readers."""

    def _iter_raw(self):
        """Yield (line_number, list_of_raw_fields), header row included."""
        raise NotImplementedError

    def _header_and_rows(self):
        rows = self._iter_raw()
        for _line_no, header in rows:
            return header, rows
        return None, rows

    def scan(self):
        null_literal = self.args.csv_null_literal
        handle_header, rows = self._header_and_rows()
        if handle_header is None:
            return [], {}
        positions = column_positions(handle_header)
        observers = {name: ColumnObserver() for name in positions}
        single_column = len(handle_header) == 1
        for _line_no, row in rows:
            if not row:
                if not single_column:
                    continue
                row = [""]
            width = len(row)
            for name, index in positions.items():
                if index >= width:
                    continue
                raw = row[index]
                if raw == "" or raw == null_literal:
                    continue          # nulls never influence inference
                observers[name].observe(raw)
        return list(positions), observers

    def iter_rows(self, columns):
        null_literal = self.args.csv_null_literal
        header, rows = self._header_and_rows()
        if header is None:
            return
        positions = column_positions(header)
        source = [positions.get(name, -1) for name in columns]
        count = len(columns)
        single_column = len(header) == 1
        for line_no, row in rows:
            if not row:
                if not single_column:
                    continue
                row = [""]
            width = len(row)
            values = [MISSING] * count
            for index in range(count):
                src = source[index]
                if src < 0 or src >= width:
                    continue
                raw = row[src]
                if raw == "" or raw == null_literal:
                    continue
                values[index] = raw
            yield f"{self.path}:{line_no}", values


class CsvSource(DelimitedSource):
    fmt = "csv"

    def _dialect(self):
        return {
            "delimiter": ",",
            "quotechar": self.args.csv_quotechar,
            "doublequote": True,
            "escapechar": self.args.csv_escapechar,
            "lineterminator": "\n",
        }

    def _iter_raw(self):
        stream = _open_text(self.path, self.compression)
        try:
            reader = csv.reader(stream, **self._dialect())
            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    return
                except csv.Error as exc:
                    raise InputError(
                        f"{self.path}:{reader.line_num}: malformed CSV: {exc}"
                    ) from None
                except (OSError, EOFError, gzip.BadGzipFile) as exc:
                    raise self._wrap_os_error(exc) from None
                yield reader.line_num, row
        finally:
            stream.close()


class TsvSource(DelimitedSource):
    fmt = "tsv"

    def _iter_raw(self):
        stream = _open_text(self.path, self.compression)
        try:
            line_no = 0
            width = None
            saw_header = False
            while True:
                try:
                    line = stream.readline()
                except (OSError, EOFError, gzip.BadGzipFile) as exc:
                    raise self._wrap_os_error(exc) from None
                if not line:
                    break
                line_no += 1
                if line.endswith("\r\n"):
                    line = line[:-2]
                elif line.endswith("\n"):
                    line = line[:-1]
                elif line.endswith("\r"):
                    line = line[:-1]
                row = line.split("\t")
                if not saw_header:
                    saw_header = True
                    width = len(row)
                    yield line_no, row
                    continue
                if len(row) > width:
                    raise InputError(
                        f"{self.path}:{line_no}: literal tab inside field "
                        f"({len(row)} fields, header declares {width})"
                    )
                yield line_no, row
            if not saw_header:
                raise InputError(f"{self.path}: TSV input has no header row")
        finally:
            stream.close()


class JsonlSource(Source):
    fmt = "jsonl"

    def _iter_objects(self):
        stream = _open_text(self.path, self.compression)
        try:
            line_no = 0
            while True:
                try:
                    line = stream.readline()
                except (OSError, EOFError, gzip.BadGzipFile) as exc:
                    raise self._wrap_os_error(exc) from None
                if not line:
                    return
                line_no += 1
                if not line.strip():
                    continue          # blank / whitespace-only lines ignored
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    raise InputError(
                        f"{self.path}:{line_no}: malformed JSON: {exc}"
                    ) from None
                if isinstance(record, list):
                    raise UnsupportedError(
                        f"{self.path}:{line_no}: nested structure: "
                        f"expected a flat JSON object, found an array"
                    )
                if not isinstance(record, dict):
                    raise InputError(
                        f"{self.path}:{line_no}: expected a JSON object, found "
                        f"{type(record).__name__}"
                    )
                for key, value in record.items():
                    if isinstance(value, (dict, list)):
                        raise UnsupportedError(
                            f"{self.path}:{line_no}: nested structure in field "
                            f"{key!r}: only flat objects are supported"
                        )
                yield line_no, record
        finally:
            stream.close()

    def scan(self):
        null_literal = self.args.csv_null_literal
        names = []
        observers = {}
        for _line_no, record in self._iter_objects():
            for key, value in record.items():
                observer = observers.get(key)
                if observer is None:
                    observer = observers[key] = ColumnObserver()
                    names.append(key)
                if value is None:
                    continue
                text = value_text(normalize_number(value))
                if text == "" or text == null_literal:
                    continue
                observer.observe(text)
        return names, observers

    def iter_rows(self, columns):
        count = len(columns)
        for line_no, record in self._iter_objects():
            values = [MISSING] * count
            for index in range(count):
                value = record.get(columns[index], MISSING)
                if value is MISSING or value is None:
                    continue
                values[index] = normalize_number(value)
            yield f"{self.path}:{line_no}", values


def _require_pyarrow():
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise MergeError(
            f"reading Parquet input requires the 'pyarrow' package: {exc}"
        ) from None
    return pq


def arrow_type_name(field_type) -> str:
    """Map an Arrow type onto one of the output schema types."""
    import pyarrow.types as pat

    if pat.is_boolean(field_type):
        return "bool"
    if pat.is_integer(field_type):
        return "int"
    if pat.is_floating(field_type) or pat.is_decimal(field_type):
        return "float"
    if pat.is_date(field_type):
        return "date"
    if pat.is_timestamp(field_type):
        return "timestamp"
    return "string"


def _is_nested(field_type) -> bool:
    import pyarrow.types as pat

    return bool(
        pat.is_list(field_type)
        or pat.is_large_list(field_type)
        or pat.is_fixed_size_list(field_type)
        or pat.is_struct(field_type)
        or pat.is_map(field_type)
        or pat.is_union(field_type)
        or (hasattr(pat, "is_nested") and pat.is_nested(field_type))
    )


class ParquetSource(Source):
    fmt = "parquet"

    def __init__(self, path, compression, args):
        super().__init__(path, compression, args)
        self._materialised = None

    def _file_path(self):
        """Parquet needs random access; gzip streams are staged on disk."""
        if self.compression != "gzip":
            return self.path
        if self._materialised is None:
            handle = tempfile.NamedTemporaryFile(
                prefix="merge_files-parquet-", suffix=".parquet",
                dir=self.args._temp_dir, delete=False,
            )
            try:
                with gzip.open(self.path, "rb") as source:
                    shutil.copyfileobj(source, handle, length=1 << 20)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                handle.close()
                _silent_remove(handle.name)
                raise InputError(f"{self.path}: corrupt gzip stream: {exc}") from None
            handle.close()
            self._materialised = handle.name
        return self._materialised

    def _open(self):
        pq = _require_pyarrow()
        try:
            return pq.ParquetFile(self._file_path(), pre_buffer=False)
        except MergeError:
            raise
        except Exception as exc:
            raise InputError(f"{self.path}: cannot read Parquet file: {exc}") from None

    def _schema(self, parquet_file):
        schema = parquet_file.schema_arrow
        for field in schema:
            if _is_nested(field.type):
                raise UnsupportedError(
                    f"{self.path}: nested structure in column {field.name!r} "
                    f"({field.type}): only flat Parquet schemas are supported"
                )
        return schema

    def scan(self):
        parquet_file = self._open()
        try:
            schema = self._schema(parquet_file)
            names, observers = [], {}
            for field in schema:
                if field.name in observers:
                    continue
                type_name = arrow_type_name(field.type)
                names.append(field.name)
                observers[field.name] = ColumnObserver(
                    DECLARED_CANDIDATES[type_name], seen=True
                )
            return names, observers
        finally:
            parquet_file.close()

    def _batch_rows(self, schema) -> int:
        import pyarrow.types as pat

        width = 0
        for field in schema:
            if pat.is_string(field.type) or pat.is_binary(field.type) or \
                    pat.is_large_string(field.type) or pat.is_large_binary(field.type):
                width += 48
            else:
                width += 16
        width = max(width, 16)
        # A fraction of the memory budget bounds one materialised batch.
        budget = max(1 << 20, self.args._memory_bytes // 8)
        target = max(1 << 20, min(self.args.parquet_row_group_bytes, budget))
        return max(1, min(16384, target // width))

    def iter_rows(self, columns):
        parquet_file = self._open()
        try:
            schema = self._schema(parquet_file)
            available = []
            for field in schema:
                if field.name not in available:
                    available.append(field.name)
            wanted = [name for name in columns if name in set(available)]
            positions = {name: index for index, name in enumerate(wanted)}
            source = [positions.get(name, -1) for name in columns]
            count = len(columns)
            batch_rows = self._batch_rows(schema)
            read_columns = wanted if wanted else available[:1]
            row_index = 0
            if not available:
                return
            try:
                batches = parquet_file.iter_batches(
                    batch_size=batch_rows, columns=read_columns, use_threads=False
                )
                for batch in batches:
                    rows = batch.num_rows
                    if not wanted:
                        for _ in range(rows):
                            row_index += 1
                            yield f"{self.path}:{row_index}", [MISSING] * count
                        continue
                    data = [column.to_pylist() for column in batch.columns]
                    for offset in range(rows):
                        row_index += 1
                        values = [MISSING] * count
                        for index in range(count):
                            src = source[index]
                            if src < 0:
                                continue
                            value = data[src][offset]
                            if value is None:
                                continue
                            values[index] = value
                        yield f"{self.path}:{row_index}", values
            except MergeError:
                raise
            except Exception as exc:
                raise InputError(
                    f"{self.path}: cannot read Parquet data: {exc}"
                ) from None
        finally:
            parquet_file.close()


SOURCE_CLASSES = {
    "csv": CsvSource,
    "tsv": TsvSource,
    "jsonl": JsonlSource,
    "parquet": ParquetSource,
}


def build_sources(paths, args):
    sources = []
    for path in paths:
        if not os.path.exists(path):
            raise UsageError(f"input file not found: {path}")
        if not os.path.isfile(path):
            raise UsageError(f"input is not a regular file: {path}")
        compression = resolve_compression(path, args.compression)
        fmt = resolve_format(path, compression, args.input_format)
        sources.append(SOURCE_CLASSES[fmt](path, compression, args))
    return sources


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

def load_schema(spec: str):
    """Load the schema from a JSON file path (or an inline JSON document)."""
    text = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as handle:
                text = handle.read()
        except OSError as exc:
            raise SchemaError(f"cannot read schema file {spec!r}: {exc}") from None
    else:
        stripped = spec.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            text = spec
        else:
            raise SchemaError(f"schema file not found: {spec}")

    try:
        document = json.loads(text)
    except ValueError as exc:
        raise SchemaError(f"invalid schema JSON: {exc}") from None

    if isinstance(document, dict):
        columns = document.get("columns")
    elif isinstance(document, list):
        columns = document
    else:
        columns = None
    if not isinstance(columns, list):
        raise SchemaError('schema must contain a "columns" array')

    names, types = [], []
    for entry in columns:
        if isinstance(entry, str):
            name, type_name = entry, "string"
        elif isinstance(entry, dict):
            name = entry.get("name")
            type_name = entry.get("type", "string")
        else:
            raise SchemaError(f"invalid schema column entry: {entry!r}")
        if not isinstance(name, str) or not name:
            raise SchemaError(f"invalid schema column name: {name!r}")
        if not isinstance(type_name, str):
            raise SchemaError(f"invalid schema column type for {name!r}")
        type_name = type_name.strip().lower()
        if type_name in ("str", "text"):
            type_name = "string"
        elif type_name in ("integer", "long"):
            type_name = "int"
        elif type_name in ("double", "decimal", "number"):
            type_name = "float"
        elif type_name == "boolean":
            type_name = "bool"
        elif type_name in ("datetime", "time"):
            type_name = "timestamp"
        if type_name not in VALID_TYPES:
            raise SchemaError(
                f"invalid type {type_name!r} for column {name!r}; "
                f"valid types: {', '.join(VALID_TYPES)}"
            )
        if name in names:
            continue  # first definition wins
        names.append(name)
        types.append(type_name)

    if not names:
        raise SchemaError("schema contains no columns")
    return names, types


def infer_schema(sources, args):
    """Infer output columns (lexicographic order) and their types."""
    all_names = set()
    entries = {}        # column -> [(rank, candidates), ...]
    for source in sources:
        names, observers = source.scan()
        all_names.update(names)
        for name, observer in observers.items():
            if observer.seen:
                entries.setdefault(name, []).append(
                    (source.rank, frozenset(observer.candidates))
                )

    columns = sorted(all_names)
    types = [
        resolve_column_type(entries.get(name, []), args.schema_strategy, args.infer)
        for name in columns
    ]
    return columns, types


# --------------------------------------------------------------------------
# External sort
# --------------------------------------------------------------------------

class _Desc:
    """Wrapper inverting the comparison of a composite key."""

    __slots__ = ("key",)

    def __init__(self, key):
        self.key = key

    def __lt__(self, other):
        return other.key < self.key

    def __eq__(self, other):
        return self.key == other.key

    def __hash__(self):
        return hash(self.key)


def _asc_sort_key(record):
    return (record[0], record[1])


def _desc_sort_key(record):
    return (_Desc(record[0]), record[1])


def _estimate_size(record) -> int:
    total = 200
    for cell in record[2]:
        total += 50 + len(cell)
    for element in record[0]:
        total += 80
    return total


def _read_run(path: str):
    with open(path, "rb", buffering=1 << 16) as handle:
        load = pickle.load
        try:
            while True:
                yield load(handle)
        except EOFError:
            return


def _write_run(path: str, records) -> None:
    with open(path, "wb", buffering=1 << 16) as handle:
        dump = pickle.dump
        for record in records:
            dump(record, handle, protocol=pickle.HIGHEST_PROTOCOL)


class ExternalSorter:
    """Collects records, spilling sorted runs to disk when memory fills up."""

    def __init__(self, temp_dir: str, budget_bytes: int, descending: bool):
        self.temp_dir = temp_dir
        self.budget = budget_bytes
        self.sort_key = _desc_sort_key if descending else _asc_sort_key
        self.buffer = []
        self.buffer_bytes = 0
        self.runs = []
        self._run_seq = 0

    def add(self, record) -> None:
        self.buffer.append(record)
        self.buffer_bytes += _estimate_size(record)
        if self.buffer_bytes >= self.budget:
            self._spill()

    def _new_run_path(self) -> str:
        self._run_seq += 1
        return os.path.join(self.temp_dir, f"run-{self._run_seq:06d}.bin")

    def _spill(self) -> None:
        if not self.buffer:
            return
        self.buffer.sort(key=self.sort_key)
        path = self._new_run_path()
        _write_run(path, self.buffer)
        self.runs.append(path)
        self.buffer = []
        self.buffer_bytes = 0

    def sorted_records(self):
        """Return an iterator over all records in sorted order."""
        if not self.runs:
            self.buffer.sort(key=self.sort_key)
            records, self.buffer = self.buffer, []
            return iter(records)

        self._spill()
        runs = self.runs
        self.runs = []
        while len(runs) > MERGE_FANOUT:
            merged_runs = []
            for start in range(0, len(runs), MERGE_FANOUT):
                group = runs[start:start + MERGE_FANOUT]
                if len(group) == 1:
                    merged_runs.append(group[0])
                    continue
                path = self._new_run_path()
                streams = [_read_run(p) for p in group]
                _write_run(path, heapq.merge(*streams, key=self.sort_key))
                for stream in streams:
                    stream.close()
                for old in group:
                    _silent_remove(old)
                merged_runs.append(path)
            runs = merged_runs
        return heapq.merge(*(_read_run(p) for p in runs), key=self.sort_key)


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------

def build_records(sources, columns, types, key_indexes, args, sorter,
                  partition_indexes=()):
    """Read every input row, cast it to the resolved schema and feed the sorter.

    With field partitioning the encoded partition values are prepended to the
    sort key, so the sorted stream groups every partition into one contiguous,
    key-sorted block that can be written in a single pass.
    """
    null_literal = args.csv_null_literal
    on_error = args.on_type_error
    count = len(columns)
    sequence = 0

    for source in sources:
        for location, values in source.iter_rows(columns):
            out_row = [null_literal] * count
            sort_values = [NULL_SORT] * count
            for index in range(count):
                value = values[index]
                if value is MISSING:
                    continue
                try:
                    sort_value, text = cast_any(value, types[index])
                except CastError:
                    if on_error == "fail":
                        raise TypeError_(
                            f"{location}: cannot cast value "
                            f"{value_text(value)!r} in column {columns[index]!r} "
                            f"to type {types[index]}"
                        )
                    if on_error == "keep-string":
                        text = value_text(value)
                        sort_value = (RANK_STR, text)
                    else:  # coerce-null
                        continue
                out_row[index] = text
                sort_values[index] = sort_value

            composite = tuple(sort_values[i] for i in key_indexes)
            if partition_indexes:
                composite = tuple(
                    NULL_PARTITION if sort_values[i] == NULL_SORT
                    else encode_partition_value(out_row[i])
                    for i in partition_indexes
                ) + composite
            sorter.add((composite, sequence, tuple(out_row)))
            sequence += 1


def csv_writer_kwargs(args):
    """The one CSV dialect every output file in a run is written with."""
    return {
        "delimiter": ",",
        "quotechar": args.csv_quotechar,
        "doublequote": True,
        "escapechar": args.csv_escapechar,
        "lineterminator": "\n",
        "quoting": csv.QUOTE_MINIMAL,
    }


def write_output(destination: str, columns, records, args):
    """Write the header and every record; files are replaced atomically."""
    writer_kwargs = csv_writer_kwargs(args)

    if destination == "-":
        stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        )
        try:
            writer = csv.writer(stream, **writer_kwargs)
            writer.writerow(columns)
            for record in records:
                writer.writerow(record[2])
            stream.flush()
        finally:
            try:
                stream.detach()
            except Exception:
                pass
        return

    directory = os.path.dirname(os.path.abspath(destination))
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise MergeError(f"cannot create output directory {directory!r}: {exc}")
    fd, temp_path = tempfile.mkstemp(
        prefix=".merge_files-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, **writer_kwargs)
            writer.writerow(columns)
            for record in records:
                writer.writerow(record[2])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            _silent_remove(temp_path)


# --------------------------------------------------------------------------
# Partitioned output
# --------------------------------------------------------------------------

# Characters kept verbatim in a Hive-style partition value; everything else is
# percent-encoded byte by byte (space -> %20, '/' -> %2F).
_PARTITION_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)

NULL_PARTITION = "_null"
PART_FILE_TEMPLATE = "part-{:05d}.csv"


def encode_partition_value(text: str) -> str:
    """Percent-encode the UTF-8 bytes of ``text`` outside [A-Za-z0-9._-]."""
    encoded = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if char in _PARTITION_SAFE:
            encoded.append(char)
        else:
            encoded.append("%%%02X" % byte)
    return "".join(encoded)


def partition_segments(columns, values):
    """Hive-style path segments ``<col>=<val>`` for one partition."""
    return [f"{name}={value}" for name, value in zip(columns, values)]


class RowFormatter:
    """Renders a row exactly as the CSV writer would, so it can be measured."""

    def __init__(self, writer_kwargs):
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer, **writer_kwargs)

    def render(self, row) -> str:
        buffer = self._buffer
        buffer.seek(0)
        buffer.truncate(0)
        self._writer.writerow(row)
        return buffer.getvalue()


class ShardWriter:
    """Writes the rows of one partition into ``part-XXXXX.csv`` shards.

    A new shard is started whenever appending the next row would break the
    row-count or byte-size limit; a row that does not fit into an empty shard
    on its own is written anyway (and that shard exceeds the byte limit).
    """

    def __init__(self, directory, header_text, formatter, max_rows, max_bytes):
        self.directory = directory
        self.header_text = header_text
        self.header_bytes = len(header_text.encode("utf-8"))
        self.formatter = formatter
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.handle = None
        self.index = 0
        self.rows = 0
        self.bytes = 0

    def _open(self) -> None:
        try:
            os.makedirs(self.directory, exist_ok=True)
        except OSError as exc:
            raise MergeError(
                f"cannot create partition directory {self.directory!r}: {exc}"
            )
        path = os.path.join(self.directory, PART_FILE_TEMPLATE.format(self.index))
        self.index += 1
        self.handle = open(path, "w", encoding="utf-8", newline="")
        self.handle.write(self.header_text)
        self.rows = 0
        self.bytes = self.header_bytes

    def _must_cut(self, size: int) -> bool:
        if self.max_rows is not None and self.rows >= self.max_rows:
            return True
        if (self.max_bytes is not None and self.rows >= 1
                and self.bytes + size > self.max_bytes):
            return True
        return False

    def write(self, row) -> None:
        text = self.formatter.render(row)
        size = len(text.encode("utf-8"))
        if self.handle is not None and self._must_cut(size):
            self.close()
        if self.handle is None:
            self._open()
        self.handle.write(text)
        self.rows += 1
        self.bytes += size

    def start(self) -> None:
        """Force an (empty) first shard so the header is always written."""
        if self.handle is None and self.index == 0:
            self._open()

    def close(self) -> None:
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        with handle:
            handle.flush()
            os.fsync(handle.fileno())


def _swap_into_place(staging: str, destination: str) -> None:
    """Move the finished staging directory onto ``destination`` atomically."""
    parent = os.path.dirname(destination) or "."
    backup = None
    if os.path.isdir(destination):
        backup = tempfile.mkdtemp(prefix=".merge_files-old-", dir=parent)
        os.rmdir(backup)
        os.rename(destination, backup)
    try:
        os.rename(staging, destination)
    except OSError as exc:
        if backup is not None:
            os.rename(backup, destination)
            backup = None
        raise MergeError(
            f"cannot move output directory into place at {destination!r}: {exc}"
        )
    finally:
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)


def write_partitioned_output(destination, columns, records, args,
                             partition_columns, register_staging):
    """Write Hive-style partitions and/or size-capped shards under a directory.

    Everything is written into a sibling temporary directory first and renamed
    onto ``destination`` once the last row landed, so readers never observe a
    partial tree; on failure the temporary directory is removed.
    """
    formatter = RowFormatter(csv_writer_kwargs(args))
    header_text = formatter.render(columns)
    depth = len(partition_columns)

    dest = os.path.abspath(destination)
    parent = os.path.dirname(dest) or "."
    if os.path.exists(dest) and not os.path.isdir(dest):
        raise UsageError(
            f"--output {destination!r} must be a directory path when "
            f"partitioning, but it is an existing file"
        )
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise MergeError(f"cannot create output directory {parent!r}: {exc}")

    staging = tempfile.mkdtemp(prefix=".merge_files-out-", dir=parent)
    register_staging(staging)
    try:
        writer = None
        current = None
        for record in records:
            segments = record[0][:depth]
            if writer is None or segments != current:
                if writer is not None:
                    writer.close()
                current = segments
                directory = staging
                for segment in partition_segments(partition_columns, segments):
                    directory = os.path.join(directory, segment)
                writer = ShardWriter(
                    directory, header_text, formatter,
                    args.max_rows_per_file, args.max_bytes_per_file,
                )
            writer.write(record[2])

        if writer is None and depth == 0:
            # No rows and no field partitioning: still emit one header-only part.
            writer = ShardWriter(
                staging, header_text, formatter,
                args.max_rows_per_file, args.max_bytes_per_file,
            )
            writer.start()
        if writer is not None:
            writer.close()

        _swap_into_place(staging, dest)
        staging = None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        register_staging(None)


def _single_char(value: str, flag: str):
    if value is None:
        return None
    if value == "":
        return None
    if len(value) != 1:
        raise UsageError(f"{flag} must be a single character, got {value!r}")
    return value


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True,
                        help="output CSV path, or '-' for stdout")
    parser.add_argument("--key", required=True, action="append",
                        help="sort key column(s); comma separated, may repeat")
    parser.add_argument("--partition-by", dest="partition_by", action="append",
                        default=None,
                        help="partition column(s); comma separated, may repeat")
    parser.add_argument("--max-rows-per-file", dest="max_rows_per_file",
                        type=int, default=None,
                        help="cut output files after this many data rows")
    parser.add_argument("--max-bytes-per-file", dest="max_bytes_per_file",
                        type=int, default=None,
                        help="cut output files at this on-disk size (bytes)")
    parser.add_argument("--desc", action="store_true",
                        help="sort all keys in descending order")
    parser.add_argument("--schema", default=None,
                        help="path to a JSON schema describing the output columns")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict",
                        help="schema inference mode when --schema is absent")
    parser.add_argument("--schema-strategy", dest="schema_strategy",
                        choices=("authoritative", "consensus", "union"),
                        default="authoritative",
                        help="how to reconcile conflicting types across inputs")
    parser.add_argument("--on-type-error", dest="on_type_error",
                        choices=("coerce-null", "fail", "keep-string"),
                        default="coerce-null",
                        help="what to do when a value cannot be cast")
    parser.add_argument("--memory-limit-mb", dest="memory_limit_mb", type=int,
                        default=256, help="approximate in-memory budget (MiB)")
    parser.add_argument("--temp-dir", dest="temp_dir", default=None,
                        help="directory for intermediate sort runs")
    parser.add_argument("--csv-quotechar", dest="csv_quotechar", default='"')
    parser.add_argument("--csv-escapechar", dest="csv_escapechar", default="\\")
    parser.add_argument("--csv-null-literal", dest="csv_null_literal", default="")
    parser.add_argument("--input-format", dest="input_format",
                        choices=("auto",) + FORMATS, default="auto",
                        help="force the format of every input (default: auto)")
    parser.add_argument("--compression", choices=("auto", "none", "gzip"),
                        default="auto",
                        help="force input compression (default: auto)")
    parser.add_argument("--parquet-row-group-bytes",
                        dest="parquet_row_group_bytes", type=int,
                        default=128 * 1024 * 1024,
                        help="advisory batch size (bytes) for Parquet reads")
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser.parse_args(argv)


def run(argv=None) -> int:
    args = parse_args(argv)

    args.csv_quotechar = _single_char(args.csv_quotechar, "--csv-quotechar") or '"'
    args.csv_escapechar = _single_char(args.csv_escapechar, "--csv-escapechar")

    keys = []
    for chunk in args.key:
        for name in chunk.split(","):
            name = name.strip()
            if name and name not in keys:
                keys.append(name)
    if not keys:
        raise UsageError("--key requires at least one column name")

    partitions = []
    if args.partition_by is not None:
        for chunk in args.partition_by:
            for name in chunk.split(","):
                name = name.strip()
                if name and name not in partitions:
                    partitions.append(name)
        if not partitions:
            raise UsageError("--partition-by requires at least one column name")

    if args.max_rows_per_file is not None and args.max_rows_per_file <= 0:
        raise UsageError("--max-rows-per-file must be a positive integer")
    if args.max_bytes_per_file is not None and args.max_bytes_per_file <= 0:
        raise UsageError("--max-bytes-per-file must be a positive integer")

    partitioned = bool(
        partitions
        or args.max_rows_per_file is not None
        or args.max_bytes_per_file is not None
    )
    if partitioned and args.output == "-":
        raise UsageError(
            "--output must be a directory path when partitioning, not '-'"
        )

    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise UsageError("--memory-limit-mb must be a positive integer")
    if args.parquet_row_group_bytes <= 0:
        raise UsageError("--parquet-row-group-bytes must be a positive integer")

    memory_bytes = max(4 * 1024 * 1024, args.memory_limit_mb * 1024 * 1024)
    budget = max(4 * 1024 * 1024, int(memory_bytes * 0.30))
    args._memory_bytes = memory_bytes

    if args.temp_dir:
        try:
            os.makedirs(args.temp_dir, exist_ok=True)
        except OSError as exc:
            raise UsageError(f"cannot create --temp-dir {args.temp_dir!r}: {exc}")
    temp_dir = tempfile.mkdtemp(prefix="merge_files-", dir=args.temp_dir)
    args._temp_dir = temp_dir

    staging = {"path": None}

    def register_staging(path):
        staging["path"] = path

    def cleanup():
        shutil.rmtree(temp_dir, ignore_errors=True)
        if staging["path"] is not None:
            shutil.rmtree(staging["path"], ignore_errors=True)
            staging["path"] = None

    atexit.register(cleanup)
    try:
        sources = build_sources(args.inputs, args)

        if args.schema:
            columns, types = load_schema(args.schema)
        else:
            columns, types = infer_schema(sources, args)

        if not columns:
            raise SchemaError("resolved schema has no columns")

        index_of = {name: i for i, name in enumerate(columns)}
        missing = [k for k in keys if k not in index_of]
        if missing:
            raise SchemaError(
                "key column(s) not present in resolved schema: " + ", ".join(missing)
            )
        key_indexes = [index_of[k] for k in keys]

        absent = [name for name in partitions if name not in index_of]
        if absent:
            raise SchemaError(
                "partition column(s) not present in resolved schema: "
                + ", ".join(absent)
            )
        partition_indexes = [index_of[name] for name in partitions]

        sorter = ExternalSorter(temp_dir, budget, args.desc)
        build_records(sources, columns, types, key_indexes, args, sorter,
                      partition_indexes)
        records = sorter.sorted_records()
        if partitioned:
            write_partitioned_output(args.output, columns, records, args,
                                     partitions, register_staging)
        else:
            write_output(args.output, columns, records, args)
    finally:
        cleanup()
        try:
            atexit.unregister(cleanup)
        except Exception:
            pass
    return 0


def _install_signal_handlers():
    def handler(signum, _frame):
        raise SystemExit(128 + signum)

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def main(argv=None) -> int:
    _install_signal_handlers()
    try:
        return run(argv)
    except MergeError as exc:
        sys.stderr.write(f"{PROG}: error: {exc}\n")
        return exc.code
    except BrokenPipeError:
        try:
            sys.stderr.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        sys.stderr.write(f"{PROG}: interrupted\n")
        return 130
    except OSError as exc:
        sys.stderr.write(f"{PROG}: error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

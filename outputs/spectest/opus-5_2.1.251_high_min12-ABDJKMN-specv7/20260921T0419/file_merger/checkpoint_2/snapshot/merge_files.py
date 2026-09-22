#!/usr/bin/env python3
"""Merge heterogeneous inputs (CSV, TSV, JSON Lines, Parquet) into one
schema-aligned, globally sorted CSV.

See AMBIGUITIES.md for the readings chosen where the spec allows more than one.
"""

from __future__ import annotations

import argparse
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
import sys
import tempfile
from datetime import date as _date
from datetime import datetime, time as _time, timedelta, timezone

PROG = "merge_files.py"

STRING = "string"
INT = "int"
FLOAT = "float"
BOOL = "bool"
DATE = "date"
TIMESTAMP = "timestamp"

VALID_TYPES = (STRING, INT, FLOAT, BOOL, DATE, TIMESTAMP)

# Highest priority first: timestamp > date > bool > int > float > string
TYPE_PRIORITY = (TIMESTAMP, DATE, BOOL, INT, FLOAT, STRING)
TYPE_BIT = {name: 1 << i for i, name in enumerate(TYPE_PRIORITY)}
ALL_BITS = (1 << len(TYPE_PRIORITY)) - 1
STRING_ONLY = TYPE_BIT[STRING]

# Bit sets contributed by an already-typed value (JSONL / Parquet). See T23.
INT_BITS = TYPE_BIT[INT] | TYPE_BIT[FLOAT] | TYPE_BIT[STRING]
FLOAT_BITS = TYPE_BIT[FLOAT] | TYPE_BIT[STRING]
BOOL_BITS = TYPE_BIT[BOOL] | TYPE_BIT[STRING]
DATE_BITS = TYPE_BIT[DATE] | TYPE_BIT[STRING]
TS_BITS = TYPE_BIT[TIMESTAMP] | TYPE_BIT[STRING]

# Sort-key ranks; nulls always compare lowest.
RANK_NULL = 0
RANK_NUMBER = 1
RANK_DATE = 2
RANK_TIMESTAMP = 3
RANK_STRING = 4

NULL_COMP = (RANK_NULL, 0)

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TS_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[Tt ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2}))?"
    r"(?:\.(?P<frac>\d+))?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)

TRUE_LITERALS = {"true", "1"}
FALSE_LITERALS = {"false", "0"}

# Input formats.
CSV = "csv"
TSV = "tsv"
JSONL = "jsonl"
PARQUET = "parquet"

EXT_FORMAT = {
    ".csv": CSV,
    ".tsv": TSV,
    ".jsonl": JSONL,
    ".ndjson": JSONL,
    ".parquet": PARQUET,
}

# Precedence tiers for --schema-strategy=authoritative (lower wins). Parquet is
# the only source whose types travel with the file; JSONL ranks with CSV (T19).
FORMAT_RANK = {PARQUET: 0, JSONL: 1, CSV: 1, TSV: 1}

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

INT64_MAX = 2 ** 63 - 1

# Exit codes (T18).
EXIT_IO = 1
EXIT_FORMAT = 2
EXIT_SCHEMA = 3
EXIT_CAST = 4
EXIT_DIALECT = 5
EXIT_NESTED = 6


class ToolError(Exception):
    """A user-facing error: reported on stderr, exits with `code`."""

    def __init__(self, message, code=EXIT_IO):
        Exception.__init__(self, message)
        self.code = code


class CastError(Exception):
    pass


class _Null:
    """Sentinel for a missing/null cell."""

    __slots__ = ()

    def __repr__(self):
        return "NULL"


NULL = _Null()


# --------------------------------------------------------------------------
# Value parsing / casting
# --------------------------------------------------------------------------


def cast_int(text):
    try:
        return int(text.strip())
    except ValueError:
        raise CastError(text)


def cast_float(text):
    try:
        return float(text.strip())
    except ValueError:
        raise CastError(text)


def cast_bool(text):
    low = text.strip().lower()
    if low in TRUE_LITERALS:
        return True
    if low in FALSE_LITERALS:
        return False
    raise CastError(text)


def cast_date(text):
    m = DATE_RE.match(text.strip())
    if not m:
        raise CastError(text)
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise CastError(text)


class Timestamp:
    """An instant normalized to UTC, remembering the source fraction digits."""

    __slots__ = ("dt", "frac")

    def __init__(self, dt, frac):
        self.dt = dt
        self.frac = frac

    def text(self):
        base = self.dt.strftime("%Y-%m-%dT%H:%M:%S")
        if self.frac:
            base += "." + self.frac
        return base + "Z"


def _parse_offset(tz):
    if tz is None:
        return timezone.utc
    if tz in ("Z", "z"):
        return timezone.utc
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    hours = int(body[:2])
    minutes = int(body[2:4]) if len(body) > 2 else 0
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def cast_timestamp(text):
    m = TS_RE.match(text.strip())
    if not m:
        raise CastError(text)
    frac = m.group("frac")
    if m.group("h") is None and (frac is not None or m.group("tz") is not None):
        # Fractional seconds or a zone without a time component is not ISO-8601.
        raise CastError(text)
    micro = int(frac[:6].ljust(6, "0")) if frac else 0
    try:
        dt = datetime(
            int(m.group("y")),
            int(m.group("mo")),
            int(m.group("d")),
            int(m.group("h") or 0),
            int(m.group("mi") or 0),
            int(m.group("s") or 0),
            micro,
            tzinfo=_parse_offset(m.group("tz")),
        )
    except ValueError:
        raise CastError(text)
    return Timestamp(dt.astimezone(timezone.utc), frac or "")


CASTERS = {
    STRING: lambda text: text,
    INT: cast_int,
    FLOAT: cast_float,
    BOOL: cast_bool,
    DATE: cast_date,
    TIMESTAMP: cast_timestamp,
}


def timestamp_from_datetime(value):
    """Normalize a datetime (naive = UTC) into a Timestamp."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    frac = "" if value.microsecond == 0 else "%06d" % value.microsecond
    return Timestamp(value, frac)


def typed_text(value):
    """Canonical text for an already-typed value; the single cast path (T33)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Timestamp):
        return value.text()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (_date, _time)):
        return value.isoformat()
    return str(value)


def format_value(type_name, value):
    if type_name == STRING:
        return value
    if type_name == BOOL:
        return "true" if value else "false"
    if type_name == DATE:
        return value.isoformat()
    if type_name == TIMESTAMP:
        return value.text()
    return str(value)


def comparable(type_name, value):
    """Sort-key component for a successfully cast value."""
    if type_name == STRING:
        return (RANK_STRING, value)
    if type_name == DATE:
        return (RANK_DATE, value)
    if type_name == TIMESTAMP:
        return (RANK_TIMESTAMP, value.dt)
    if type_name == BOOL:
        return (RANK_NUMBER, 1 if value else 0)
    return (RANK_NUMBER, value)


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------


def looks_like_timestamp(text):
    m = TS_RE.match(text.strip())
    if not m or m.group("h") is None:
        # Inference keeps bare dates for the `date` type; a timestamp needs a
        # time component (otherwise `date` would be unreachable).
        return False
    try:
        cast_timestamp(text)
    except CastError:
        return False
    return True


def candidate_bits(text):
    """Set of types `text` could be, as a bitmask (string is always possible)."""
    bits = TYPE_BIT[STRING]
    stripped = text.strip()
    if looks_like_timestamp(text):
        bits |= TYPE_BIT[TIMESTAMP]
    elif DATE_RE.match(stripped):
        try:
            cast_date(text)
            bits |= TYPE_BIT[DATE]
        except CastError:
            pass
    low = stripped.lower()
    if low in TRUE_LITERALS or low in FALSE_LITERALS:
        bits |= TYPE_BIT[BOOL]
    try:
        int(stripped)
        bits |= TYPE_BIT[INT]
    except ValueError:
        pass
    try:
        number = float(stripped)
    except ValueError:
        pass
    else:
        # `nan`/`inf` are words far more often than they are numbers.
        if number == number and number not in (float("inf"), float("-inf")):
            bits |= TYPE_BIT[FLOAT]
    return bits


def value_bits(value):
    """Types an observed value fits, or None when it is not an observation."""
    if value is NULL:
        return None
    if isinstance(value, str):
        if value == "":
            return None
        return candidate_bits(value)
    if isinstance(value, bool):
        return BOOL_BITS
    if isinstance(value, int):
        return INT_BITS
    if isinstance(value, float):
        return FLOAT_BITS
    if isinstance(value, Timestamp):
        return TS_BITS
    if isinstance(value, _date):
        return DATE_BITS
    return STRING_ONLY


def top_type(bits):
    for name in TYPE_PRIORITY:
        if bits & TYPE_BIT[name]:
            return name
    return STRING


def widen(masks):
    """Simplest type able to hold every observed value (T21)."""
    bits = ALL_BITS
    for mask in masks:
        bits &= mask
    chosen = top_type(bits)
    if chosen == STRING:
        # Every date is representable as a timestamp, which the per-value bit
        # sets (deliberately) do not encode, so promote that one pairing.
        kinds = {top_type(mask) for mask in masks}
        if kinds and kinds <= {DATE, TIMESTAMP}:
            return TIMESTAMP
    return chosen


def resolve_column_type(entries, strategy, infer_mode):
    """entries: list of (format rank, bitmask) for the files that saw the column."""
    if not entries:
        return STRING
    masks = [mask for _rank, mask in entries]
    if strategy == "union":
        return widen(masks)
    if strategy == "consensus":
        votes = {}
        for mask in masks:
            name = top_type(mask)
            votes[name] = votes.get(name, 0) + 1
        best = max(votes.values())
        tied = [name for name in TYPE_PRIORITY if votes.get(name, 0) == best]
        return tied[0]
    # authoritative: only the highest-precedence tier that saw the column votes.
    best_rank = min(rank for rank, _mask in entries)
    masks = [mask for rank, mask in entries if rank == best_rank]
    if infer_mode == "loose":
        return widen(masks)
    kinds = {top_type(mask) for mask in masks}
    return kinds.pop() if len(kinds) == 1 else STRING


# --------------------------------------------------------------------------
# Input specs: format & compression detection
# --------------------------------------------------------------------------


class InputSpec:
    __slots__ = ("path", "fmt", "compression", "scratch", "_local")

    def __init__(self, path, fmt, compression, scratch=None):
        self.path = path
        self.fmt = fmt
        self.compression = compression
        self.scratch = scratch
        self._local = None

    @property
    def rank(self):
        return FORMAT_RANK[self.fmt]

    def local_parquet_path(self):
        """A seekable, uncompressed copy of a gzipped parquet file."""
        if self.compression != "gzip":
            return self.path
        if self._local is None:
            handle = tempfile.NamedTemporaryFile(
                prefix="merge_files-", suffix=".parquet", dir=self.scratch,
                delete=False,
            )
            with handle:
                with gzip.open(self.path, "rb") as source:
                    shutil.copyfileobj(source, handle, 1024 * 1024)
            self._local = handle.name
        return self._local


def read_magic(path, length=4):
    try:
        with open(path, "rb") as handle:
            return handle.read(length)
    except OSError as exc:
        raise ToolError("cannot read input %s: %s" % (path, exc.strerror or exc))


def is_gzip_file(path):
    return read_magic(path, 2) == GZIP_MAGIC


def is_parquet_file(path, compression):
    if compression == "gzip":
        try:
            with gzip.open(path, "rb") as handle:
                return handle.read(4) == PARQUET_MAGIC
        except OSError:
            return False
    return read_magic(path, 4) == PARQUET_MAGIC


def resolve_compression(path, flag):
    actual = is_gzip_file(path)
    if flag == "gzip":
        if not actual:
            raise ToolError(
                "compression mismatch: %s is not gzip-compressed" % path,
                EXIT_DIALECT,
            )
        return "gzip"
    if flag == "none":
        if actual:
            raise ToolError(
                "compression mismatch: %s is gzip-compressed" % path, EXIT_DIALECT
            )
        return "none"
    # auto
    if path.lower().endswith(".gz") and not actual:
        raise ToolError(
            "compression mismatch: %s has a .gz suffix but is not gzip-compressed"
            % path,
            EXIT_DIALECT,
        )
    return "gzip" if actual else "none"


def resolve_format(path, flag, compression):
    if flag != "auto":
        return flag
    name = os.path.basename(path)
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    _stem, ext = os.path.splitext(lowered)
    fmt = EXT_FORMAT.get(ext)
    if fmt is not None:
        return fmt
    if is_parquet_file(path, compression):
        return PARQUET
    raise ToolError(
        "cannot determine input format for %s (use --input-format)" % path,
        EXIT_FORMAT,
    )


def make_specs(args, scratch):
    specs = []
    for path in args.inputs:
        if not os.path.exists(path):
            raise ToolError("input file not found: %s" % path)
        compression = resolve_compression(path, args.compression)
        fmt = resolve_format(path, args.input_format, compression)
        specs.append(InputSpec(path, fmt, compression, scratch))
    return specs


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


class Dialect:
    def __init__(self, quotechar, escapechar, null_literal):
        self.quotechar = quotechar
        self.escapechar = escapechar
        self.null_literal = null_literal


def open_text(spec, newline):
    try:
        if spec.compression == "gzip":
            binary = gzip.open(spec.path, "rb")
        else:
            binary = open(spec.path, "rb")
    except OSError as exc:
        raise ToolError(
            "cannot read input %s: %s" % (spec.path, exc.strerror or exc)
        )
    return io.TextIOWrapper(binary, encoding="utf-8-sig", newline=newline)


def wrap_os_error(spec, exc):
    return ToolError("cannot read input %s: %s" % (spec.path, exc))


def make_csv_reader(handle, dialect):
    return csv.reader(
        handle,
        delimiter=",",
        quotechar=dialect.quotechar,
        doublequote=True,
        escapechar=dialect.escapechar,
        strict=False,
    )


def is_null_text(cell, null_literal):
    if cell == "":
        return True
    return bool(null_literal) and cell == null_literal


def iter_delimited(spec, dialect):
    """Yield (line_number, header, cells) for a CSV or TSV input.

    The header is yielded once as the first item with cells set to None.
    """
    if spec.fmt == CSV:
        handle = open_text(spec, "")
        try:
            reader = make_csv_reader(handle, dialect)
            header = None
            line = 1
            for row in reader:
                if header is None:
                    header = list(row)
                    yield (1, header, None)
                    continue
                line += 1
                if not row:
                    continue
                yield (line, header, row)
            if header is None:
                yield (1, [], None)
        except csv.Error as exc:
            raise ToolError(
                "%s: malformed CSV: %s" % (spec.path, exc), EXIT_DIALECT
            )
        finally:
            handle.close()
        return

    handle = open_text(spec, "\n")
    try:
        header = None
        line = 0
        for raw in handle:
            line += 1
            text = raw.rstrip("\n")
            if text.endswith("\r"):
                text = text[:-1]
            if header is None:
                header = text.split("\t")
                yield (1, header, None)
                continue
            if text == "":
                continue
            cells = text.split("\t")
            if len(cells) > len(header):
                raise ToolError(
                    "%s:%d: literal tab inside a TSV field (%d fields, header has %d)"
                    % (spec.path, line, len(cells), len(header)),
                    EXIT_DIALECT,
                )
            yield (line, header, cells)
        if header is None:
            raise ToolError(
                "%s: TSV input has no header row" % spec.path, EXIT_DIALECT
            )
    finally:
        handle.close()


def header_positions(header, columns):
    lookup = {}
    for pos, name in enumerate(header):
        lookup.setdefault(name, pos)
    return [lookup.get(name) for name in columns]


def iter_jsonl(spec):
    """Yield (line_number, dict) for each JSON object in a JSONL input."""
    handle = open_text(spec, "\n")
    try:
        line = 0
        for raw in handle:
            line += 1
            text = raw.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except ValueError as exc:
                raise ToolError(
                    "%s:%d: invalid JSON: %s" % (spec.path, line, exc), EXIT_DIALECT
                )
            if not isinstance(record, dict):
                raise ToolError(
                    "%s:%d: JSONL line is not a JSON object" % (spec.path, line),
                    EXIT_DIALECT,
                )
            for name, value in record.items():
                if isinstance(value, (list, dict)):
                    raise ToolError(
                        "%s:%d: nested value for field %r (JSONL objects must be flat)"
                        % (spec.path, line, name),
                        EXIT_NESTED,
                    )
            yield line, {
                name: jsonl_value(value) for name, value in record.items()
            }
    finally:
        handle.close()


def jsonl_value(value):
    if value is None:
        return NULL
    if isinstance(value, float):
        # Prefer int for integral numbers inside the int64 range (T24).
        if math.isfinite(value) and value.is_integer() and abs(value) <= INT64_MAX:
            return int(value)
    return value


def import_pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet as parquet
        import pyarrow.types as types
    except ImportError as exc:
        raise ToolError("reading Parquet input requires pyarrow: %s" % exc)
    return parquet, types


def parquet_file(spec):
    parquet, types = import_pyarrow()
    path = spec.local_parquet_path()
    try:
        handle = parquet.ParquetFile(path)
    except Exception as exc:
        raise ToolError(
            "%s: cannot read Parquet file: %s" % (spec.path, exc), EXIT_DIALECT
        )
    schema = handle.schema_arrow
    for field in schema:
        if types.is_nested(field.type):
            raise ToolError(
                "%s: nested Parquet field %r of type %s (flat schemas only)"
                % (spec.path, field.name, field.type),
                EXIT_NESTED,
            )
    return handle, schema, types


def arrow_bits(field_type, types):
    """Bitmask for a Parquet column type, or None when values must be sniffed."""
    if types.is_boolean(field_type):
        return BOOL_BITS
    if types.is_integer(field_type):
        return INT_BITS
    if types.is_floating(field_type) or types.is_decimal(field_type):
        return FLOAT_BITS
    if types.is_date(field_type):
        return DATE_BITS
    if types.is_timestamp(field_type):
        return TS_BITS
    if (
        types.is_string(field_type)
        or types.is_large_string(field_type)
        or types.is_binary(field_type)
        or types.is_large_binary(field_type)
    ):
        return None
    return STRING_ONLY


def parquet_batch_rows(args):
    rows = max(1, args.parquet_row_group_bytes // 1024)
    budget = max(1, (args.memory_limit_mb * 1024 * 1024) // 4096)
    return max(1, min(rows, budget, 65536))


def convert_parquet(value):
    if value is None:
        return NULL
    if isinstance(value, datetime):
        return timestamp_from_datetime(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def iter_parquet(spec, args, columns):
    """Yield (row_number, values) with values aligned to `columns`."""
    handle, schema, _types = parquet_file(spec)
    names = list(schema.names)
    wanted = [name for name in columns if name in names]
    index = {name: pos for pos, name in enumerate(wanted)}
    positions = [index.get(name) for name in columns]
    blank = [NULL] * len(columns)
    row = 0
    try:
        if not wanted:
            for batch in handle.iter_batches(batch_size=parquet_batch_rows(args)):
                for _ in range(batch.num_rows):
                    row += 1
                    yield row, list(blank)
            return
        for batch in handle.iter_batches(
            batch_size=parquet_batch_rows(args), columns=wanted
        ):
            chunks = [column.to_pylist() for column in batch.columns]
            for offset in range(batch.num_rows):
                row += 1
                values = [
                    NULL if pos is None else convert_parquet(chunks[pos][offset])
                    for pos in positions
                ]
                yield row, values
    finally:
        handle.close()


# --------------------------------------------------------------------------
# Per-file scanning for inference
# --------------------------------------------------------------------------


def scan_file(spec, args, dialect):
    """One pass over an input: (field names, {name: bitmask of fitting types})."""
    if spec.fmt == PARQUET:
        return scan_parquet(spec, args)
    masks = {}
    if spec.fmt == JSONL:
        names = []
        seen = set()
        for _line, record in iter_jsonl(spec):
            for name, value in record.items():
                if name not in seen:
                    seen.add(name)
                    names.append(name)
                observe(masks, name, value_bits(value))
        return names, masks

    names = None
    for _line, header, cells in iter_delimited(spec, dialect):
        if cells is None:
            names = header
            continue
        for pos, name in enumerate(names):
            if pos >= len(cells):
                break
            cell = cells[pos]
            if is_null_text(cell, dialect.null_literal):
                continue
            observe(masks, name, candidate_bits(cell))
    return names or [], masks


def observe(masks, name, bits):
    if bits is None:
        return
    previous = masks.get(name, ALL_BITS)
    # `string` fits everything, so it is the floor: once a column is down to it,
    # further values cannot narrow it.
    if previous != STRING_ONLY:
        previous &= bits
    masks[name] = previous


def scan_parquet(spec, args):
    """Parquet types come from the file schema; only string columns are sniffed."""
    handle, schema, types = parquet_file(spec)
    names = list(schema.names)
    masks = {}
    sniff = []
    for field in schema:
        bits = arrow_bits(field.type, types)
        if bits is None:
            sniff.append(field.name)
            masks[field.name] = STRING_ONLY
        else:
            masks[field.name] = bits
    try:
        if sniff:
            for name in sniff:
                masks.pop(name, None)
            for batch in handle.iter_batches(
                batch_size=parquet_batch_rows(args), columns=sniff
            ):
                for position, name in enumerate(sniff):
                    column = batch.column(position).to_pylist()
                    for value in column:
                        observe(masks, name, value_bits(convert_parquet(value)))
            for name in sniff:
                masks.setdefault(name, STRING_ONLY)
    finally:
        handle.close()
    return names, masks


def iter_rows(spec, args, dialect, columns):
    """Yield (line number, values aligned to `columns`) for one input."""
    if spec.fmt == PARQUET:
        for item in iter_parquet(spec, args, columns):
            yield item
        return
    if spec.fmt == JSONL:
        for line, record in iter_jsonl(spec):
            yield line, [record.get(name, NULL) for name in columns]
        return
    positions = None
    null_literal = dialect.null_literal
    for line, header, cells in iter_delimited(spec, dialect):
        if cells is None:
            positions = header_positions(header, columns)
            continue
        size = len(cells)
        values = []
        for pos in positions:
            if pos is None or pos >= size:
                values.append(NULL)
                continue
            cell = cells[pos]
            values.append(NULL if is_null_text(cell, null_literal) else cell)
        yield line, values


# --------------------------------------------------------------------------
# Sorting
# --------------------------------------------------------------------------


class Reversed:
    """Wrapper inverting the order of a key component (for --desc)."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return other.value < self.value

    def __hash__(self):
        return hash(self.value)


def make_sort_key(desc):
    if desc:
        def key(record):
            return (tuple(Reversed(part) for part in record[0]), record[1])
    else:
        def key(record):
            return (record[0], record[1])
    return key


def iter_chunk(path):
    """Stream one spilled run back. A fresh unpickler per record keeps the
    memo from retaining the whole run in memory."""
    with open(path, "rb") as handle:
        load = pickle.load
        while True:
            try:
                yield load(handle)
            except EOFError:
                return


MAX_FANIN = 64  # bound on run files merged (and open) at once


class ExternalSorter:
    """Chunked sort: buffer records, spill sorted runs, then k-way merge."""

    def __init__(self, temp_dir, memory_limit_mb, desc):
        self.temp_dir = temp_dir
        self.budget = max(64 * 1024, int(memory_limit_mb * 1024 * 1024 * 0.15))
        self.sort_key = make_sort_key(desc)
        self.buffer = []
        self.used = 0
        self.runs = []
        self.created = []

    def add(self, record):
        self.buffer.append(record)
        self.used += 128 + sum(len(cell) + 56 for cell in record[2])
        if self.used >= self.budget:
            self.spill()

    def spill(self):
        if not self.buffer:
            return
        self.buffer.sort(key=self.sort_key)
        handle = self.new_run()
        self.runs.append(handle.name)
        with handle:
            dump = pickle.dump
            protocol = pickle.HIGHEST_PROTOCOL
            for record in self.buffer:
                dump(record, handle, protocol)
        self.buffer = []
        self.used = 0

    def new_run(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="merge_files-", suffix=".run", dir=self.temp_dir, delete=False
        )
        self.created.append(handle.name)
        return handle

    def merge_runs(self, runs):
        """Merge a group of runs into a single new run file."""
        handle = self.new_run()
        with handle:
            dump = pickle.dump
            protocol = pickle.HIGHEST_PROTOCOL
            for record in heapq.merge(
                *(iter_chunk(path) for path in runs), key=self.sort_key
            ):
                dump(record, handle, protocol)
        for path in runs:
            try:
                os.unlink(path)
            except OSError:
                pass
        return handle.name

    def sorted_records(self):
        if not self.runs:
            self.buffer.sort(key=self.sort_key)
            return iter(self.buffer)
        self.spill()
        while len(self.runs) > MAX_FANIN:
            merged = []
            for start in range(0, len(self.runs), MAX_FANIN):
                group = self.runs[start:start + MAX_FANIN]
                merged.append(group[0] if len(group) == 1 else self.merge_runs(group))
            self.runs = merged
        return heapq.merge(
            *(iter_chunk(path) for path in self.runs), key=self.sort_key
        )

    def cleanup(self):
        for path in self.created:
            try:
                os.unlink(path)
            except OSError:
                pass
        self.created = []
        self.runs = []
        self.buffer = []


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------


def parse_schema_document(document, origin):
    if not isinstance(document, dict) or not isinstance(
        document.get("columns"), list
    ):
        raise ToolError(
            "schema %s must be an object with a 'columns' list" % origin, EXIT_SCHEMA
        )
    columns = []
    types = {}
    for entry in document["columns"]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ToolError(
                "schema column entries need a 'name': %r" % (entry,), EXIT_SCHEMA
            )
        name = entry["name"]
        type_name = entry.get("type", STRING)
        if type_name not in VALID_TYPES:
            raise ToolError(
                "invalid column type %r for column %r (valid: %s)"
                % (type_name, name, ", ".join(VALID_TYPES)),
                EXIT_SCHEMA,
            )
        columns.append(name)
        types[name] = type_name
    return columns, types


def load_schema(source):
    """`source` is a path to a JSON document, or the document itself (T28)."""
    if not os.path.exists(source) and source.lstrip().startswith("{"):
        try:
            document = json.loads(source)
        except ValueError as exc:
            raise ToolError("invalid inline schema JSON: %s" % exc, EXIT_SCHEMA)
        return parse_schema_document(document, "<inline>")
    try:
        with open(source, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise ToolError("cannot read schema %s: %s" % (source, exc.strerror or exc))
    except ValueError as exc:
        raise ToolError(
            "invalid schema JSON in %s: %s" % (source, exc), EXIT_SCHEMA
        )
    return parse_schema_document(document, source)


def resolve_schema(specs, args, dialect):
    if args.schema:
        return load_schema(args.schema)
    names = set()
    per_file = []
    for spec in specs:
        file_names, masks = scan_file(spec, args, dialect)
        names.update(file_names)
        names.update(masks)
        per_file.append((spec.rank, masks))
    columns = sorted(names)
    types = {}
    for name in columns:
        entries = [
            (rank, masks[name]) for rank, masks in per_file if name in masks
        ]
        types[name] = resolve_column_type(
            entries, args.schema_strategy, args.infer
        )
    return columns, types


# --------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------


def build_records(specs, args, columns, types, dialect, sorter):
    """Cast every input cell, feeding sortable records to the sorter."""
    null_literal = dialect.null_literal
    key_positions = [columns.index(name) for name in args.key]
    column_types = [types[name] for name in columns]
    casters = [CASTERS[name] for name in column_types]
    seq = 0
    for spec in specs:
        for line, values in iter_rows(spec, args, dialect, columns):
            out_row = []
            comps = []
            for offset, value in enumerate(values):
                if value is NULL:
                    out_row.append(null_literal)
                    comps.append(NULL_COMP)
                    continue
                type_name = column_types[offset]
                text = value if isinstance(value, str) else typed_text(value)
                try:
                    cast = text if type_name == STRING else casters[offset](text)
                except CastError:
                    if args.on_type_error == "fail":
                        raise ToolError(
                            "%s:%d: cannot cast %r to %s for column %r"
                            % (spec.path, line, text, type_name, columns[offset]),
                            EXIT_CAST,
                        )
                    if args.on_type_error == "keep-string":
                        out_row.append(text)
                        comps.append((RANK_STRING, text))
                    else:
                        out_row.append(null_literal)
                        comps.append(NULL_COMP)
                    continue
                out_row.append(format_value(type_name, cast))
                comps.append(comparable(type_name, cast))
            key = tuple(comps[pos] for pos in key_positions)
            sorter.add((key, seq, out_row))
            seq += 1


def make_writer(stream, dialect):
    # The quote character is honoured on output; escaping stays doubling, so the
    # escape character is an input-side concession only (T29).
    return csv.writer(
        stream,
        delimiter=",",
        quotechar=dialect.quotechar,
        doublequote=True,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )


def write_rows(stream, columns, records, dialect):
    writer = make_writer(stream, dialect)
    writer.writerow(columns)
    for _key, _seq, row in records:
        writer.writerow(row)
    stream.flush()


def write_output(destination, columns, records, dialect):
    if destination == "-":
        stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        )
        try:
            write_rows(stream, columns, records, dialect)
        finally:
            try:
                stream.detach()
            except Exception:
                pass
        return

    folder = os.path.dirname(os.path.abspath(destination))
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=folder,
            prefix=".merge_files-", suffix=".tmp", delete=False,
        )
    except OSError as exc:
        raise ToolError(
            "cannot write output %s: %s" % (destination, exc.strerror or exc)
        )
    temp_name = handle.name
    try:
        with handle:
            write_rows(handle, columns, records, dialect)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def single_char(value):
    if len(value) != 1:
        raise argparse.ArgumentTypeError("expected a single character, got %r" % value)
    return value


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer, got %r" % value)
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer, got %r" % value)
    return number


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
        help="comma-separated sort key column(s)",
    )
    parser.add_argument(
        "--desc", action="store_true", help="sort all key columns descending"
    )
    parser.add_argument("--schema", help="JSON file (or document) with the schema")
    parser.add_argument(
        "--infer", choices=("strict", "loose"), default="strict",
        help="type inference mode when no schema is given",
    )
    parser.add_argument(
        "--schema-strategy",
        choices=("authoritative", "consensus", "union"),
        default="authoritative",
        help="how to reconcile conflicting types across inputs",
    )
    parser.add_argument(
        "--on-type-error",
        choices=("coerce-null", "fail", "keep-string"),
        default="coerce-null",
    )
    parser.add_argument("--memory-limit-mb", type=positive_int, default=128)
    parser.add_argument("--temp-dir", help="directory for intermediate files")
    parser.add_argument("--csv-quotechar", type=single_char, default='"')
    parser.add_argument("--csv-escapechar", type=single_char, default="\\")
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument(
        "--input-format",
        choices=("auto", CSV, TSV, JSONL, PARQUET),
        default="auto",
    )
    parser.add_argument(
        "--compression", choices=("auto", "none", "gzip"), default="auto"
    )
    parser.add_argument(
        "--parquet-row-group-bytes", type=positive_int, default=128 * 1024 * 1024,
        help="advisory batch size when reading Parquet row groups",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


def parse_args(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    keys = []
    for group in args.key:
        for name in group.split(","):
            name = name.strip()
            if not name:
                parser.error("--key must name at least one column")
            keys.append(name)
    args.key = keys
    if args.temp_dir is not None and not os.path.isdir(args.temp_dir):
        parser.error("--temp-dir %s is not a directory" % args.temp_dir)
    return args


def run(args):
    dialect = Dialect(args.csv_quotechar, args.csv_escapechar, args.csv_null_literal)
    scratch = tempfile.mkdtemp(prefix="merge_files-", dir=args.temp_dir)
    sorter = ExternalSorter(scratch, args.memory_limit_mb, args.desc)
    try:
        specs = make_specs(args, scratch)
        columns, types = resolve_schema(specs, args, dialect)
        missing = [name for name in args.key if name not in columns]
        if missing:
            raise ToolError(
                "key column(s) not present in resolved schema: %s"
                % ", ".join(missing),
                EXIT_SCHEMA,
            )
        build_records(specs, args, columns, types, dialect, sorter)
        write_output(args.output, columns, sorter.sorted_records(), dialect)
    finally:
        sorter.cleanup()
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except ToolError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return exc.code
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_IO
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

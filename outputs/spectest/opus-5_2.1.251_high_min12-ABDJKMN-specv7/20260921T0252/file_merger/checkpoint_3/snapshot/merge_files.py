#!/usr/bin/env python3
"""Multi-format merger and sorter.

Ingests multiple CSV, TSV, JSON Lines and Parquet files (optionally gzip
compressed), reconciles their schemas (provided or inferred), casts cells to
the resolved types and emits a globally sorted CSV.

The output is either a single CSV (file or stdout) or, when any partitioning
flag is given, a directory of ``part-xxxxx.csv`` shards laid out in Hive-style
``<col>=<value>`` subdirectories.

Sorting is done with an external merge sort and every reader is streaming, so
inputs far larger than ``--memory-limit-mb`` can be processed; the partitioned
writer streams the sorted result straight to disk.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import heapq
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import date as date_cls
from datetime import datetime, timezone

VALID_TYPES = ("string", "int", "float", "bool", "date", "timestamp")
# Highest priority first.
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

INT_RE = re.compile(r"^[+-]?[0-9]+$")
FLOAT_RE = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

BOOL_TRUE = frozenset({"true", "1"})
BOOL_FALSE = frozenset({"false", "0"})

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

# Exit codes (see AMBIGUITIES.md T18).
EXIT_OK = 0
EXIT_ERROR = 1          # I/O and otherwise unclassified failures
EXIT_USAGE = 2          # bad arguments, undetectable input format
EXIT_SCHEMA = 3         # schema problems, unknown key column
EXIT_CAST = 4           # cast failure under --on-type-error=fail
EXIT_DIALECT = 5        # source dialect / compression violation
EXIT_NESTED = 6         # nested structures in JSONL or Parquet

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

EXT_FORMATS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}

# Types a value of a declared type can also be rendered/cast as.
TYPE_CLOSURE = {
    "string": frozenset({"string"}),
    "int": frozenset({"int", "float", "string"}),
    "float": frozenset({"float", "string"}),
    "bool": frozenset({"bool", "string"}),
    "date": frozenset({"date", "string"}),
    "timestamp": frozenset({"timestamp", "string"}),
}

# Source precedence for --schema-strategy=authoritative (lower ranks win).
FORMAT_RANK = {"parquet": 0, "jsonl": 1, "csv": 1, "tsv": 1}


class UserError(Exception):
    """A user facing error; reported on stderr with a specific exit code."""

    def __init__(self, message, code=EXIT_ERROR):
        Exception.__init__(self, message)
        self.code = code


# --------------------------------------------------------------------------
# Dialect options
# --------------------------------------------------------------------------
class Options(object):
    __slots__ = ("quotechar", "escapechar", "null_literal", "row_group_bytes")

    def __init__(self, quotechar, escapechar, null_literal, row_group_bytes):
        self.quotechar = quotechar
        self.escapechar = escapechar
        self.null_literal = null_literal
        self.row_group_bytes = row_group_bytes


# --------------------------------------------------------------------------
# Format and compression detection
# --------------------------------------------------------------------------
def read_head(path, count):
    try:
        with open(path, "rb") as fh:
            return fh.read(count)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc), EXIT_ERROR)


def read_inner_head(path, comp, count):
    """First bytes of the (possibly decompressed) payload."""
    if comp != "gzip":
        return read_head(path, count)
    try:
        with gzip.open(path, "rb") as fh:
            return fh.read(count)
    except OSError as exc:
        raise UserError("cannot read gzip input %s: %s" % (path, exc),
                        EXIT_DIALECT)
    except EOFError as exc:
        raise UserError("truncated gzip input %s: %s" % (path, exc),
                        EXIT_DIALECT)


def detect_file(path, forced_format, forced_compression):
    """Return ``(format, compression)`` for one input path."""
    name = os.path.basename(path).lower()
    has_gz = name.endswith(".gz")

    if forced_compression == "auto":
        comp = "gzip" if has_gz else "none"
    else:
        comp = forced_compression

    head = read_head(path, 2)
    looks_gzip = head[:2] == GZIP_MAGIC
    if comp == "gzip" and not looks_gzip:
        raise UserError(
            "compression mismatch: %s is not gzip compressed" % path,
            EXIT_DIALECT)
    if comp == "none" and looks_gzip:
        raise UserError(
            "compression mismatch: %s is gzip compressed" % path,
            EXIT_DIALECT)

    if forced_format != "auto":
        return forced_format, comp

    base = name[:-3] if has_gz else name
    _stem, ext = os.path.splitext(base)
    fmt = EXT_FORMATS.get(ext)
    if fmt is not None:
        return fmt, comp

    if read_inner_head(path, comp, 4) == PARQUET_MAGIC:
        return "parquet", comp
    raise UserError(
        "cannot determine input format for %s (unrecognised extension and "
        "no Parquet magic bytes)" % path, EXIT_USAGE)


# --------------------------------------------------------------------------
# Parsing / casting primitives
# --------------------------------------------------------------------------
def p_string(raw):
    return raw


def p_int(raw):
    text = raw.strip()
    if not INT_RE.match(text):
        raise ValueError(raw)
    return int(text)


def p_float(raw):
    text = raw.strip()
    if not FLOAT_RE.match(text):
        raise ValueError(raw)
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(raw)
    return value


def p_bool(raw):
    text = raw.strip().lower()
    if text in BOOL_TRUE:
        return True
    if text in BOOL_FALSE:
        return False
    raise ValueError(raw)


def p_date(raw):
    text = raw.strip()
    m = DATE_RE.match(text)
    if not m:
        raise ValueError(raw)
    try:
        return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise ValueError(raw)


def parse_datetime(raw):
    """Parse an ISO-8601 date-time (time component required)."""
    text = raw.strip()
    m = TS_RE.match(text)
    if not m:
        raise ValueError(raw)
    iso = m.group(1) + "T" + m.group(2)
    zone = m.group(3)
    if zone:
        upper = zone.upper()
        if upper == "Z":
            iso += "+00:00"
        else:
            if len(upper) == 5:  # +HHMM
                upper = upper[:3] + ":" + upper[3:]
            iso += upper
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def p_timestamp(raw):
    """Cast to timestamp; a bare date is accepted as midnight UTC."""
    try:
        return parse_datetime(raw)
    except ValueError:
        day = p_date(raw)
        return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


PARSERS = {
    "string": p_string,
    "int": p_int,
    "float": p_float,
    "bool": p_bool,
    "date": p_date,
    "timestamp": p_timestamp,
}


def r_string(value):
    return value


def r_int(value):
    return str(value)


def r_float(value):
    return repr(value)


def r_bool(value):
    return "true" if value else "false"


def r_date(value):
    return value.isoformat()


def r_timestamp(value):
    return value.replace(tzinfo=None).isoformat() + "Z"


RENDERERS = {
    "string": r_string,
    "int": r_int,
    "float": r_float,
    "bool": r_bool,
    "date": r_date,
    "timestamp": r_timestamp,
}


def s_timestamp(value):
    return value.replace(tzinfo=None).isoformat(timespec="microseconds")


SORTERS = {
    "string": lambda v: v,
    "int": lambda v: v,
    "float": lambda v: v,
    "bool": lambda v: v,
    "date": lambda v: v.isoformat(),
    "timestamp": s_timestamp,
}


# --------------------------------------------------------------------------
# Cells
#
# A cell is either ``None`` (the source had no value at all) or a
# ``(kind, text)`` pair.  ``kind`` is "text" for CSV/TSV cells, "json" for
# JSONL values, and the declared type name for Parquet values.
# --------------------------------------------------------------------------
def candidate_types(raw):
    """Set of types the raw text can be recognised as."""
    text = raw.strip()
    found = {"string"}
    if TS_RE.match(text):
        try:
            parse_datetime(text)
            found.add("timestamp")
        except ValueError:
            pass
    if DATE_RE.match(text):
        try:
            p_date(text)
            found.add("date")
        except ValueError:
            pass
    if text.lower() in BOOL_TRUE or text.lower() in BOOL_FALSE:
        found.add("bool")
    if INT_RE.match(text):
        found.add("int")
    if FLOAT_RE.match(text):
        try:
            p_float(text)
            found.add("float")
        except ValueError:
            pass
    return found


def cell_is_null(cell, null_literal):
    """CSV/TSV text cells are null when empty or equal to the null literal."""
    if cell is None:
        return True
    kind, text = cell
    if kind == "text":
        return text == "" or text == null_literal
    return False


def cell_candidates(cell):
    kind, text = cell
    if kind in ("text", "json"):
        return candidate_types(text)
    return set(TYPE_CLOSURE[kind])


def best_type(candidates):
    for name in TYPE_PRIORITY:
        if name in candidates:
            return name
    return "string"


def widen(left, right):
    """Simplest common type that can hold values of both types."""
    if left == right:
        return left
    pair = frozenset((left, right))
    if pair == frozenset(("int", "float")):
        return "float"
    if pair == frozenset(("date", "timestamp")):
        return "timestamp"
    return "string"


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------
def open_text(path, comp):
    try:
        if comp == "gzip":
            return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
        return open(path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc), EXIT_ERROR)


def iter_text_lines(path, comp):
    """Yield ``(lineno, line)`` with the line terminator stripped."""
    handle = open_text(path, comp)
    try:
        lineno = 0
        while True:
            try:
                raw = handle.readline()
            except UnicodeDecodeError as exc:
                raise UserError("%s is not valid UTF-8 text: %s"
                                % (path, exc), EXIT_DIALECT)
            except (OSError, EOFError) as exc:
                raise UserError("cannot read %s: %s" % (path, exc),
                                EXIT_DIALECT)
            if raw == "":
                return
            lineno += 1
            line = raw.rstrip("\n")
            if line.endswith("\r"):
                line = line[:-1]
            yield lineno, line
    finally:
        handle.close()


def parse_csv_line(line, opts):
    """Split one physical CSV line into fields (RFC-4180 plus backslashes)."""
    quotechar = opts.quotechar
    escapechar = opts.escapechar
    fields = []
    cur = []
    in_quotes = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_quotes:
            if (
                escapechar
                and ch == escapechar
                and i + 1 < n
                and line[i + 1] in (quotechar, escapechar)
            ):
                cur.append(line[i + 1])
                i += 2
                continue
            if ch == quotechar:
                if i + 1 < n and line[i + 1] == quotechar:
                    cur.append(quotechar)
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            cur.append(ch)
            i += 1
            continue
        if ch == ",":
            fields.append("".join(cur))
            cur = []
            i += 1
            continue
        if ch == quotechar and not cur:
            in_quotes = True
            i += 1
            continue
        cur.append(ch)
        i += 1
    fields.append("".join(cur))
    return fields


def iter_delimited(path, comp, split):
    """Yield ``(lineno, fields)``; blank lines trailing the file are dropped."""
    pending = []
    for lineno, line in iter_text_lines(path, comp):
        if line == "":
            pending.append(lineno)
            continue
        for blank in pending:
            yield blank, [""]
        pending = []
        yield lineno, split(line)


def header_index(fields):
    """Map column name -> first index in the header."""
    index = {}
    for pos, name in enumerate(fields):
        if name not in index:
            index[name] = pos
    return index


def iter_text_rows(path, fmt, comp, opts):
    """Yield ``(lineno, header_names, {column: cell})`` for CSV/TSV."""
    if fmt == "tsv":
        split = lambda line: line.split("\t")
    else:
        split = lambda line: parse_csv_line(line, opts)

    index = None
    names = None
    for lineno, fields in iter_delimited(path, comp, split):
        if index is None:
            names = list(fields)
            index = header_index(fields)
            continue
        if fmt == "tsv" and len(fields) > len(names):
            raise UserError(
                "%s:%d: literal tab inside a TSV field (%d fields, header "
                "has %d)" % (path, lineno, len(fields), len(names)),
                EXIT_DIALECT)
        row = {}
        for name, pos in index.items():
            row[name] = ("text", fields[pos] if pos < len(fields) else "")
        yield lineno, names, row
    if index is None:
        if fmt == "tsv":
            raise UserError("%s has no header row" % path, EXIT_DIALECT)
        yield None, [], None


def json_cell(path, lineno, key, value):
    """Convert one JSON value into a cell."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        raise UserError(
            "%s:%d: field %r holds a nested %s; JSONL objects must be flat"
            % (path, lineno, key,
               "array" if isinstance(value, list) else "object"),
            EXIT_NESTED)
    if isinstance(value, bool):
        return ("json", "true" if value else "false")
    if isinstance(value, int):
        if INT64_MIN <= value <= INT64_MAX:
            return ("json", str(value))
        try:
            return ("json", repr(float(value)))
        except OverflowError:
            return ("json", repr(math.inf if value > 0 else -math.inf))
    if isinstance(value, float):
        if value == value and abs(value) != math.inf and value.is_integer():
            as_int = int(value)
            if INT64_MIN <= as_int <= INT64_MAX:
                return ("json", str(as_int))
        return ("json", repr(value))
    return ("json", value)


def iter_jsonl_rows(path, comp, opts):
    """Yield ``(lineno, key_order, {column: cell})`` for JSON Lines."""
    for lineno, line in iter_text_lines(path, comp):
        if line.strip() == "":
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            raise UserError("%s:%d: invalid JSON (%s)" % (path, lineno, exc),
                            EXIT_DIALECT)
        if not isinstance(obj, dict):
            raise UserError(
                "%s:%d: each JSONL line must hold a JSON object"
                % (path, lineno), EXIT_DIALECT)
        row = {}
        for key, value in obj.items():
            row[key] = json_cell(path, lineno, key, value)
        yield lineno, list(obj.keys()), row


# --------------------------------------------------------------------------
# Parquet
# --------------------------------------------------------------------------
_PARQUET_MODULES = {}


def load_parquet():
    if "pq" not in _PARQUET_MODULES:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            raise UserError(
                "reading Parquet input requires the pyarrow package",
                EXIT_ERROR)
        _PARQUET_MODULES["pa"] = pa
        _PARQUET_MODULES["pq"] = pq
    return _PARQUET_MODULES["pa"], _PARQUET_MODULES["pq"]


def parquet_type(pa, path, name, dtype):
    if (pa.types.is_list(dtype) or pa.types.is_large_list(dtype)
            or pa.types.is_fixed_size_list(dtype)
            or pa.types.is_struct(dtype) or pa.types.is_map(dtype)
            or pa.types.is_union(dtype) or pa.types.is_nested(dtype)):
        raise UserError(
            "%s: column %r has nested type %s; Parquet inputs must be flat"
            % (path, name, dtype), EXIT_NESTED)
    if pa.types.is_boolean(dtype):
        return "bool"
    if pa.types.is_integer(dtype):
        return "int"
    if pa.types.is_floating(dtype) or pa.types.is_decimal(dtype):
        return "float"
    if pa.types.is_date(dtype):
        return "date"
    if pa.types.is_timestamp(dtype):
        return "timestamp"
    return "string"


def parquet_path(path, comp, scratch):
    """Return a plain on-disk Parquet path, decompressing when needed."""
    if comp != "gzip":
        return path
    key = os.path.abspath(path)
    if key in scratch:
        return scratch[key]
    fd, plain = tempfile.mkstemp(suffix=".parquet", dir=scratch["__dir__"])
    try:
        with os.fdopen(fd, "wb") as out:
            with gzip.open(path, "rb") as src:
                shutil.copyfileobj(src, out, 1 << 20)
    except (OSError, EOFError) as exc:
        raise UserError("cannot decompress %s: %s" % (path, exc),
                        EXIT_DIALECT)
    scratch[key] = plain
    return plain


def parquet_schema(path, comp, scratch):
    """Return ``[(position, name, type), ...]``, first occurrence per name.

    Parquet permits repeated field names, so columns are addressed by
    position and a repeated name resolves to its first field.
    """
    pa, pq = load_parquet()
    plain = parquet_path(path, comp, scratch)
    try:
        handle = pq.ParquetFile(plain)
    except Exception as exc:
        raise UserError("cannot read Parquet file %s: %s" % (path, exc),
                        EXIT_DIALECT)
    schema = handle.schema_arrow
    handle.close()
    columns = []
    seen = set()
    for position, field in enumerate(schema):
        col_type = parquet_type(pa, path, field.name, field.type)
        if field.name in seen:
            continue
        seen.add(field.name)
        columns.append((position, field.name, col_type))
    return columns


def parquet_value_cell(col_type, value):
    if value is None:
        return None
    if col_type == "bool":
        return ("bool", "true" if value else "false")
    if col_type == "int":
        return ("int", str(int(value)))
    if col_type == "float":
        return ("float", repr(float(value)))
    if col_type == "date":
        if isinstance(value, datetime):
            value = value.date()
        return ("date", value.isoformat())
    if col_type == "timestamp":
        if isinstance(value, date_cls) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return ("timestamp", r_timestamp(value.astimezone(timezone.utc)))
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = value.decode("utf-8", "replace")
    return ("string", value if isinstance(value, str) else str(value))


def parquet_batch_size(columns, row_group_bytes):
    """Advisory batch sizing: keep one record batch near the byte budget."""
    per_row = max(32, 64 * max(1, len(columns)))
    size = int(row_group_bytes) // per_row
    return max(1, min(8192, size))


def iter_parquet_rows(path, comp, opts, scratch):
    """Yield ``(rownum, names, {column: cell})`` row group by row group."""
    pa, pq = load_parquet()
    columns = parquet_schema(path, comp, scratch)
    names = [name for _pos, name, _type in columns]
    plain = parquet_path(path, comp, scratch)
    batch_size = parquet_batch_size(names, opts.row_group_bytes)
    try:
        handle = pq.ParquetFile(plain)
    except Exception as exc:
        raise UserError("cannot read Parquet file %s: %s" % (path, exc),
                        EXIT_DIALECT)
    rownum = 0
    try:
        for batch in handle.iter_batches(batch_size=batch_size):
            series = [(name, col_type, batch.column(pos))
                      for pos, name, col_type in columns]
            for i in range(batch.num_rows):
                rownum += 1
                row = {}
                for name, col_type, values in series:
                    row[name] = parquet_value_cell(col_type,
                                                   values[i].as_py())
                yield rownum, names, row
    except UserError:
        raise
    except Exception as exc:
        raise UserError("cannot read Parquet file %s: %s" % (path, exc),
                        EXIT_DIALECT)
    finally:
        handle.close()


# --------------------------------------------------------------------------
# One input source
# --------------------------------------------------------------------------
class Source(object):
    __slots__ = ("path", "fmt", "comp", "opts", "scratch")

    def __init__(self, path, fmt, comp, opts, scratch):
        self.path = path
        self.fmt = fmt
        self.comp = comp
        self.opts = opts
        self.scratch = scratch

    @property
    def rank(self):
        return FORMAT_RANK.get(self.fmt, 1)

    def iter_rows(self):
        """Yield ``(location, {column: cell})`` for every data row."""
        if self.fmt == "parquet":
            for rownum, _names, row in iter_parquet_rows(
                    self.path, self.comp, self.opts, self.scratch):
                yield "row %d" % rownum, row
        elif self.fmt == "jsonl":
            for lineno, _names, row in iter_jsonl_rows(
                    self.path, self.comp, self.opts):
                yield "line %d" % lineno, row
        else:
            for lineno, _names, row in iter_text_rows(
                    self.path, self.fmt, self.comp, self.opts):
                if row is None:
                    continue
                yield "line %d" % lineno, row

    def observe(self, mode, null_literal):
        """Return ``(column names, {column: candidate set or None})``.

        ``None`` means the column exists in the source but contributed no
        type information (every value was null under ``loose``).
        """
        if self.fmt == "parquet":
            columns = parquet_schema(self.path, self.comp, self.scratch)
            names = [name for _pos, name, _type in columns]
            cands = dict((name, set(TYPE_CLOSURE[col_type]))
                         for _pos, name, col_type in columns)
            return names, cands

        names = []
        seen = set()
        cands = {}
        if self.fmt == "jsonl":
            rows = iter_jsonl_rows(self.path, self.comp, self.opts)
        else:
            rows = iter_text_rows(self.path, self.fmt, self.comp, self.opts)
        for _lineno, row_names, row in rows:
            for name in row_names:
                if name not in seen:
                    seen.add(name)
                    names.append(name)
                    cands.setdefault(name, None)
            if row is None:
                continue
            for name, cell in row.items():
                if mode == "loose" and cell_is_null(cell, null_literal):
                    continue
                if cell is None:
                    found = {"string"}
                else:
                    found = cell_candidates(cell)
                current = cands.get(name)
                cands[name] = found if current is None else (current & found)
        return names, cands


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------
def resolve_column(observations, strategy, mode):
    """Pick one type from ``[(rank, candidates), ...]`` for a column."""
    useful = [(rank, cand) for rank, cand in observations if cand]
    if not useful:
        return "string"

    if strategy == "authoritative":
        top = min(rank for rank, _cand in useful)
        chosen = [cand for rank, cand in useful if rank == top]
        if mode == "loose":
            merged = set(chosen[0])
            for cand in chosen[1:]:
                merged &= cand
            return best_type(merged)
        types = set(best_type(cand) for cand in chosen)
        if len(types) == 1:
            return types.pop()
        return "string"

    if strategy == "consensus":
        total = len(useful)
        counts = {}
        for _rank, cand in useful:
            for name in cand:
                counts[name] = counts.get(name, 0) + 1
        majority = set(name for name, count in counts.items()
                       if count * 2 > total)
        return best_type(majority)

    # union
    result = None
    for _rank, cand in useful:
        col_type = best_type(cand)
        result = col_type if result is None else widen(result, col_type)
    return result or "string"


def infer_schema(sources, strategy, mode, null_literal):
    columns = set()
    observations = {}
    for source in sources:
        names, cands = source.observe(mode, null_literal)
        columns.update(names)
        for name in names:
            observations.setdefault(name, []).append(
                (source.rank, cands.get(name)))
    return [(name, resolve_column(observations.get(name, []), strategy, mode))
            for name in sorted(columns)]


def load_schema(spec):
    text = spec.strip()
    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise UserError("invalid inline schema JSON: %s" % exc,
                            EXIT_SCHEMA)
    else:
        try:
            with open(spec, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError as exc:
            raise UserError("cannot read schema %s: %s" % (spec, exc),
                            EXIT_SCHEMA)
        except ValueError as exc:
            raise UserError("invalid schema JSON in %s: %s" % (spec, exc),
                            EXIT_SCHEMA)
    if isinstance(doc, list):
        doc = {"columns": doc}
    if not isinstance(doc, dict) or not isinstance(doc.get("columns"), list):
        raise UserError("schema must be an object with a 'columns' list",
                        EXIT_SCHEMA)
    resolved = []
    names = set()
    for entry in doc["columns"]:
        if not isinstance(entry, dict):
            raise UserError("each schema column must be an object",
                            EXIT_SCHEMA)
        name = entry.get("name")
        col_type = entry.get("type", "string")
        if not isinstance(name, str) or name == "":
            raise UserError("schema column is missing a 'name'", EXIT_SCHEMA)
        if col_type not in VALID_TYPES:
            raise UserError(
                "unknown type %r for column %r (valid: %s)"
                % (col_type, name, ", ".join(VALID_TYPES)), EXIT_SCHEMA)
        if name in names:
            raise UserError("duplicate schema column %r" % name, EXIT_SCHEMA)
        names.add(name)
        resolved.append((name, col_type))
    return resolved


# --------------------------------------------------------------------------
# Records and ordering
# --------------------------------------------------------------------------
_DESC = False

NULL_KEY = (0, 0, "")


class Rec(object):
    __slots__ = ("key", "seq", "cells", "pnull")

    def __init__(self, key, seq, cells, pnull=0):
        self.key = key
        self.seq = seq
        self.cells = cells
        # Bit *i* is set when the i-th --partition-by column is missing for
        # this row.  Nullness has to travel with the record because the
        # rendered text of a null is indistinguishable from an empty string
        # once the null literal is empty (see AMBIGUITIES.md T40).
        self.pnull = pnull

    def __lt__(self, other):
        if self.key != other.key:
            if _DESC:
                return self.key > other.key
            return self.key < other.key
        # Stable with respect to input appearance for equal keys.
        return self.seq < other.seq


def cast_cell(cell, col_type, on_type_error, null_literal, where):
    """Return ``(output_text, key_component)`` for one cell."""
    if cell_is_null(cell, null_literal):
        return null_literal, NULL_KEY
    _kind, raw = cell
    try:
        value = PARSERS[col_type](raw)
    except ValueError:
        if on_type_error == "fail":
            raise UserError(
                "cannot cast %r to %s (%s)" % (raw, col_type, where),
                EXIT_CAST)
        if on_type_error == "keep-string":
            return raw, (1, 1, raw)
        return null_literal, NULL_KEY
    return RENDERERS[col_type](value), (1, 0, SORTERS[col_type](value))


# --------------------------------------------------------------------------
# External merge sort
# --------------------------------------------------------------------------
def spill(records, temp_dir, chunk_paths):
    records.sort()
    fd, path = tempfile.mkstemp(suffix=".chunk", dir=temp_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps([rec.key, rec.seq, rec.cells, rec.pnull])
                     + "\n")
    chunk_paths.append(path)
    del records[:]


def read_chunk(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            key, seq, cells, pnull = json.loads(line)
            yield Rec(tuple(tuple(part) for part in key), seq, cells, pnull)


def estimate_size(cells):
    total = 160
    for cell in cells:
        total += len(cell) + 56
    return total


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def current_umask():
    value = os.umask(0)
    os.umask(value)
    return value


def make_writer(stream, opts):
    return csv.writer(stream, delimiter=",", quotechar=opts.quotechar,
                      doublequote=True, escapechar=None,
                      quoting=csv.QUOTE_MINIMAL, lineterminator="\n")


def write_output(destination, col_names, ordered, opts):
    if destination == "-":
        writer = make_writer(sys.stdout, opts)
        writer.writerow(col_names)
        for rec in ordered:
            writer.writerow(rec.cells)
        sys.stdout.flush()
        return

    target = os.path.abspath(destination)
    parent = os.path.dirname(target) or "."
    try:
        fd, tmp = tempfile.mkstemp(prefix=".merge_files_", suffix=".tmp",
                                   dir=parent)
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc),
                        EXIT_ERROR)
    try:
        os.chmod(tmp, 0o666 & ~current_umask())
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            writer = make_writer(out, opts)
            writer.writerow(col_names)
            for rec in ordered:
                writer.writerow(rec.cells)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
        tmp = None
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc),
                        EXIT_ERROR)
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


# --------------------------------------------------------------------------
# Partitioned / sharded directory output
# --------------------------------------------------------------------------
PART_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
NULL_SEGMENT = "_null"
PART_NAME = "part-%05d.csv"
# Cap on simultaneously open part files; wide partitionings reopen on demand.
MAX_OPEN_PARTS = 32


def encode_partition_value(text):
    """Percent-encode the UTF-8 bytes outside ``[A-Za-z0-9._-]``."""
    out = []
    for byte in text.encode("utf-8"):
        ch = chr(byte)
        if ch in PART_SAFE:
            out.append(ch)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


class RowFormatter(object):
    """Render rows exactly as the single-file writer would, as bytes."""

    def __init__(self, opts):
        self.buf = io.StringIO()
        self.writer = make_writer(self.buf, opts)

    def row(self, cells):
        self.buf.seek(0)
        self.buf.truncate(0)
        self.writer.writerow(cells)
        return self.buf.getvalue().encode("utf-8")


class PartState(object):
    __slots__ = ("directory", "index", "rows", "size", "path", "full")

    def __init__(self, directory):
        self.directory = directory
        self.index = 0
        self.rows = 0
        self.size = 0
        self.path = None
        # Set once a lone oversized row has been written: it must stay alone.
        self.full = False


class PartitionedWriter(object):
    """Route a sorted stream into Hive directories and size/row shards."""

    def __init__(self, root, header, max_rows, max_bytes, file_mode):
        self.root = root
        self.header = header
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.file_mode = file_mode
        self.states = {}
        self.open_handles = collections.OrderedDict()

    # -- file handles ------------------------------------------------------
    def _evict(self):
        while len(self.open_handles) >= MAX_OPEN_PARTS:
            _key, handle = self.open_handles.popitem(last=False)
            handle.close()

    def _handle(self, segments, state):
        handle = self.open_handles.get(segments)
        if handle is not None:
            self.open_handles.move_to_end(segments)
            return handle
        self._evict()
        handle = open(state.path, "ab")
        self.open_handles[segments] = handle
        return handle

    def _close(self, segments):
        handle = self.open_handles.pop(segments, None)
        if handle is not None:
            handle.close()

    # -- partitions --------------------------------------------------------
    def state(self, segments):
        state = self.states.get(segments)
        if state is None:
            directory = self.root
            for segment in segments:
                directory = os.path.join(directory, segment)
            if segments:
                os.makedirs(directory, exist_ok=True)
                os.chmod(directory, 0o777 & ~current_umask())
            state = PartState(directory)
            self.states[segments] = state
        return state

    def roll(self, segments, state):
        """Start the next ``part-xxxxx.csv`` of one partition."""
        self._close(segments)
        state.path = os.path.join(state.directory, PART_NAME % state.index)
        state.index += 1
        self._evict()
        handle = open(state.path, "wb")
        self.open_handles[segments] = handle
        os.chmod(state.path, self.file_mode)
        handle.write(self.header)
        state.rows = 0
        state.size = len(self.header)
        state.full = False

    def _cut(self, state, nbytes):
        if state.rows == 0:
            return False
        if self.max_rows is not None and state.rows + 1 > self.max_rows:
            return True
        if self.max_bytes is not None and state.size + nbytes > self.max_bytes:
            return True
        return False

    def write(self, segments, data):
        state = self.state(segments)
        if state.path is None or state.full or self._cut(state, len(data)):
            self.roll(segments, state)
        handle = self._handle(segments, state)
        handle.write(data)
        state.rows += 1
        state.size += len(data)
        if self.max_bytes is not None and state.size > self.max_bytes:
            # The row did not fit even in a fresh file; it stays alone.
            state.full = True

    def ensure(self, segments):
        """Create a header-only part file for an otherwise empty partition."""
        state = self.state(segments)
        if state.path is None:
            self.roll(segments, state)

    def close(self):
        while self.open_handles:
            _key, handle = self.open_handles.popitem()
            handle.close()


def commit_directory(staging, target, destination):
    """Atomically move the staged tree onto *target*."""
    backup = None
    try:
        if os.path.exists(target):
            backup = staging + ".old"
            os.rename(target, backup)
        os.rename(staging, target)
    except OSError as exc:
        if backup is not None and not os.path.exists(target):
            try:
                os.rename(backup, target)
            except OSError:
                pass
        raise UserError("cannot write output %s: %s" % (destination, exc),
                        EXIT_ERROR)
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def write_partitioned(destination, col_names, ordered, opts, part_slots,
                      max_rows, max_bytes):
    target = os.path.abspath(destination)
    parent = os.path.dirname(target) or "."
    if os.path.exists(target) and not os.path.isdir(target):
        raise UserError(
            "cannot write output %s: exists and is not a directory"
            % destination, EXIT_ERROR)
    try:
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".merge_files_", suffix=".tmp",
                                   dir=parent)
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc),
                        EXIT_ERROR)

    dir_mode = 0o777 & ~current_umask()
    file_mode = 0o666 & ~current_umask()
    try:
        os.chmod(staging, dir_mode)
        fmt = RowFormatter(opts)
        header = fmt.row(col_names)
        writer = PartitionedWriter(staging, header, max_rows, max_bytes,
                                   file_mode)
        labels = [col_names[idx] for idx in part_slots]
        try:
            for rec in ordered:
                segments = []
                for slot, idx in enumerate(part_slots):
                    if (rec.pnull >> slot) & 1:
                        value = NULL_SEGMENT
                    else:
                        value = encode_partition_value(rec.cells[idx])
                    segments.append("%s=%s" % (labels[slot], value))
                writer.write(tuple(segments), fmt.row(rec.cells))
            if not part_slots:
                # A sharded run with no rows still emits one header-only file.
                writer.ensure(())
        finally:
            writer.close()
    except UserError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UserError("cannot write output %s: %s" % (destination, exc),
                        EXIT_ERROR)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    try:
        commit_directory(staging, target, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSONL and Parquet files into one "
                    "sorted CSV.",
    )
    parser.add_argument("--output", required=True,
                        help="output path, or - for stdout")
    parser.add_argument("--key", required=True, action="append",
                        help="comma separated sort key column(s)")
    parser.add_argument("--partition-by", action="append", default=None,
                        help="comma separated Hive partition column(s)")
    parser.add_argument("--max-rows-per-file", type=int, default=None,
                        help="cut part files after this many data rows")
    parser.add_argument("--max-bytes-per-file", type=int, default=None,
                        help="cut part files at this on-disk byte size")
    parser.add_argument("--desc", action="store_true",
                        help="sort all keys descending")
    parser.add_argument("--schema", default=None,
                        help="JSON schema document, or a path to one")
    parser.add_argument("--infer", choices=("strict", "loose"),
                        default="strict")
    parser.add_argument("--schema-strategy",
                        choices=("authoritative", "consensus", "union"),
                        default="authoritative")
    parser.add_argument("--on-type-error",
                        choices=("coerce-null", "fail", "keep-string"),
                        default="coerce-null")
    parser.add_argument("--memory-limit-mb", type=int, default=64)
    parser.add_argument("--temp-dir", default=None)
    parser.add_argument("--csv-quotechar", default='"')
    parser.add_argument("--csv-escapechar", default="\\")
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument("--input-format",
                        choices=("auto", "csv", "tsv", "jsonl", "parquet"),
                        default="auto")
    parser.add_argument("--compression", choices=("auto", "none", "gzip"),
                        default="auto")
    parser.add_argument("--parquet-row-group-bytes", type=int,
                        default=64 * 1024 * 1024)
    parser.add_argument("inputs", nargs="+")
    return parser


def resolve_keys(key_args, schema):
    keys = []
    for chunk in key_args:
        for part in chunk.split(","):
            name = part.strip()
            if name == "":
                raise UserError("empty key column name", EXIT_SCHEMA)
            if name not in keys:
                keys.append(name)
    names = [name for name, _ in schema]
    for name in keys:
        if name not in names:
            raise UserError(
                "key column %r is not present in the resolved schema" % name,
                EXIT_SCHEMA)
    return keys


def resolve_partitions(part_args, schema):
    """Ordered, de-duplicated --partition-by column names."""
    if not part_args:
        return []
    cols = []
    for chunk in part_args:
        for piece in chunk.split(","):
            name = piece.strip()
            if name == "":
                raise UserError("empty partition column name", EXIT_SCHEMA)
            if name not in cols:
                cols.append(name)
    names = [name for name, _ in schema]
    for name in cols:
        if name not in names:
            raise UserError(
                "partition column %r is not present in the resolved schema"
                % name, EXIT_SCHEMA)
    return cols


def run(args):
    global _DESC
    _DESC = bool(args.desc)

    quotechar = args.csv_quotechar
    if len(quotechar) != 1:
        raise UserError("--csv-quotechar must be a single character",
                        EXIT_USAGE)
    escapechar = args.csv_escapechar
    if len(escapechar) > 1:
        raise UserError("--csv-escapechar must be a single character",
                        EXIT_USAGE)
    if escapechar == "":
        escapechar = None
    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise UserError("--memory-limit-mb must be positive", EXIT_USAGE)
    if args.parquet_row_group_bytes <= 0:
        raise UserError("--parquet-row-group-bytes must be positive",
                        EXIT_USAGE)
    if args.max_rows_per_file is not None and args.max_rows_per_file <= 0:
        raise UserError("--max-rows-per-file must be positive", EXIT_USAGE)
    if args.max_bytes_per_file is not None and args.max_bytes_per_file <= 0:
        raise UserError("--max-bytes-per-file must be positive", EXIT_USAGE)
    partitioned = bool(args.partition_by
                       or args.max_rows_per_file is not None
                       or args.max_bytes_per_file is not None)
    if partitioned and args.output == "-":
        raise UserError(
            "--output must be a directory path, not -, when --partition-by, "
            "--max-rows-per-file or --max-bytes-per-file is used",
            EXIT_USAGE)

    null_literal = args.csv_null_literal
    opts = Options(quotechar, escapechar, null_literal,
                   args.parquet_row_group_bytes)

    for path in args.inputs:
        if not os.path.isfile(path):
            raise UserError("input file not found: %s" % path, EXIT_ERROR)

    temp_parent = args.temp_dir
    if temp_parent:
        try:
            os.makedirs(temp_parent, exist_ok=True)
        except OSError as exc:
            raise UserError("cannot use --temp-dir %s: %s"
                            % (temp_parent, exc), EXIT_ERROR)
    temp_dir = tempfile.mkdtemp(prefix="merge_files_", dir=temp_parent)
    scratch = {"__dir__": temp_dir}

    try:
        sources = []
        for path in args.inputs:
            fmt, comp = detect_file(path, args.input_format, args.compression)
            sources.append(Source(path, fmt, comp, opts, scratch))

        if args.schema:
            schema = load_schema(args.schema)
        else:
            schema = infer_schema(sources, args.schema_strategy, args.infer,
                                  null_literal)

        keys = resolve_keys(args.key, schema)
        part_cols = resolve_partitions(args.partition_by, schema)
        col_names = [name for name, _ in schema]
        col_types = [ctype for _, ctype in schema]
        key_slots = {}
        for slot, name in enumerate(keys):
            key_slots.setdefault(col_names.index(name), []).append(slot)
        part_slots = [col_names.index(name) for name in part_cols]
        part_bits = {}
        for slot, index in enumerate(part_slots):
            part_bits[index] = slot

        budget = max(int(args.memory_limit_mb * 1024 * 1024 * 0.25), 65536)

        chunk_paths = []
        buffer = []
        used = 0
        seq = 0
        for source in sources:
            for location, row in source.iter_rows():
                cells = []
                key_parts = [None] * len(keys)
                pnull = 0
                for col, name in enumerate(col_names):
                    cell = row.get(name)
                    where = "%s %s column %r" % (source.path, location, name)
                    text, keypart = cast_cell(
                        cell, col_types[col], args.on_type_error,
                        null_literal, where)
                    cells.append(text)
                    for slot in key_slots.get(col, ()):
                        key_parts[slot] = keypart
                    if col in part_bits and keypart == NULL_KEY:
                        pnull |= 1 << part_bits[col]
                buffer.append(Rec(tuple(key_parts), seq, cells, pnull))
                seq += 1
                used += estimate_size(cells)
                if used >= budget:
                    spill(buffer, temp_dir, chunk_paths)
                    used = 0

        if chunk_paths and buffer:
            spill(buffer, temp_dir, chunk_paths)

        if chunk_paths:
            ordered = heapq.merge(*[read_chunk(p) for p in chunk_paths])
        else:
            buffer.sort()
            ordered = iter(buffer)

        if partitioned:
            write_partitioned(args.output, col_names, ordered, opts,
                              part_slots, args.max_rows_per_file,
                              args.max_bytes_per_file)
        else:
            write_output(args.output, col_names, ordered, opts)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return EXIT_OK


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except UserError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return exc.code
    except BrokenPipeError:
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

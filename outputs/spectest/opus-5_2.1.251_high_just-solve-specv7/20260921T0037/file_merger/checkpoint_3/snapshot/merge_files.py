#!/usr/bin/env python3
"""
Multi-format merger and sorter.

Ingests multiple heterogeneous inputs (CSV, TSV, JSON Lines, Parquet),
reconciles their schemas (provided or inferred), casts every cell to the
resolved types and emits a single globally-sorted CSV.

Sorting is done with an external merge sort and every reader is streaming,
so inputs far larger than ``--memory-limit-mb`` can be processed. All
temporary resources are removed on exit.
"""

from __future__ import annotations

import argparse
import atexit
import gzip
import heapq
import io
import json
import operator
import os
import re
import shutil
import sys
import tempfile
from datetime import date as _date, datetime, time as _time, timedelta, timezone
from decimal import Decimal

# --------------------------------------------------------------------------
# Exit codes
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_TYPE = 1        # cast failure under --on-type-error=fail
EXIT_USAGE = 2       # bad CLI / schema / undetectable input format
EXIT_KEY = 3         # --key column absent from the resolved schema
EXIT_IO = 4          # missing or unreadable input / output
EXIT_DIALECT = 5     # malformed source, or compression mismatch
EXIT_NESTED = 6      # non-flat JSONL object or Parquet schema

# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------

# Highest priority first: timestamp > date > bool > int > float > string
TYPE_ORDER = ("timestamp", "date", "bool", "int", "float", "string")
TYPE_BIT = {name: 1 << i for i, name in enumerate(TYPE_ORDER)}
ALL_BITS = (1 << len(TYPE_ORDER)) - 1
STR_BIT = TYPE_BIT["string"]
VALID_TYPES = frozenset(TYPE_ORDER)

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

INT_RE = re.compile(r"^[+-]?[0-9]+$")
FLOAT_RE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"           # date
    r"[Tt ]"                               # separator
    r"(\d{2}):(\d{2})(?::(\d{2}))?"        # time
    r"(\.\d+)?"                            # fractional seconds
    r"(Z|z|[+-]\d{2}:\d{2}|[+-]\d{2}\d{2}|[+-]\d{2})?$"  # offset
)
BOOL_TRUE = frozenset(("true", "1"))
BOOL_FALSE = frozenset(("false", "0"))


class CastError(Exception):
    """Raised when a cell cannot be cast into the requested type."""


# --------------------------------------------------------------------------
# Value parsers.  Each returns (sort_value, output_text).
# --------------------------------------------------------------------------

def parse_int(text):
    t = text.strip()
    if not INT_RE.match(t):
        raise CastError("int")
    v = int(t)
    return v, str(v)


def parse_float(text):
    t = text.strip()
    if not FLOAT_RE.match(t):
        raise CastError("float")
    v = float(t)
    return v, format_float(v)


def format_float(v):
    # repr() gives the shortest round-trippable form and keeps a ".0" on
    # integral values so the column stays visibly float-typed.
    return repr(v)


def parse_bool(text):
    t = text.strip().lower()
    if t in BOOL_TRUE:
        return True, "true"
    if t in BOOL_FALSE:
        return False, "false"
    raise CastError("bool")


def parse_date(text):
    t = text.strip()
    m = DATE_RE.match(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            _date(y, mo, d)
        except ValueError:
            raise CastError("date")
        out = "%04d-%02d-%02d" % (y, mo, d)
        return out, out
    # A full timestamp may be narrowed to its (UTC) calendar date.
    dt, _frac = _parse_ts_parts(t)
    out = "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)
    return out, out


def _parse_ts_parts(text):
    """Parse an ISO-8601 timestamp; return (utc datetime, fraction string)."""
    t = text.strip()
    m = TS_RE.match(t)
    if not m:
        # Allow a bare date: treat as midnight UTC.
        dm = DATE_RE.match(t)
        if dm:
            try:
                return datetime(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)),
                                tzinfo=timezone.utc), ""
            except ValueError:
                raise CastError("timestamp")
        raise CastError("timestamp")

    year, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour, minute = int(m.group(4)), int(m.group(5))
    sec = int(m.group(6)) if m.group(6) else 0
    frac = m.group(7) or ""
    off = m.group(8)

    micro = 0
    if frac:
        digits = frac[1:]
        micro = int((digits + "000000")[:6])

    try:
        dt = datetime(year, mon, day, hour, minute, sec, micro)
    except ValueError:
        raise CastError("timestamp")

    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        oh = int(body[:2])
        om = int(body[2:4]) if len(body) >= 4 else 0
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    dt = dt.replace(tzinfo=timezone.utc)
    return dt, frac


def _ts_render(dt, frac):
    base = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    out = base + frac + "Z"
    # Sort key: fixed-width fraction so lexicographic order is chronological.
    digits = (frac[1:] if frac else "")
    key = base + "." + (digits + "000000000")[:9]
    return key, out


def parse_timestamp(text):
    dt, frac = _parse_ts_parts(text)
    return _ts_render(dt, frac)


def parse_string(text):
    return text, text


PARSERS = {
    "int": parse_int,
    "float": parse_float,
    "bool": parse_bool,
    "date": parse_date,
    "timestamp": parse_timestamp,
    "string": parse_string,
}


def value_mask(text):
    """Bitmask of the types ``text`` can be represented as."""
    mask = STR_BIT
    t = text.strip()
    if not t:
        return mask
    if INT_RE.match(t):
        mask |= TYPE_BIT["int"] | TYPE_BIT["float"]
        if t in ("0", "1"):
            mask |= TYPE_BIT["bool"]
        return mask
    low = t.lower()
    if low in ("true", "false"):
        return mask | TYPE_BIT["bool"]
    if FLOAT_RE.match(t):
        return mask | TYPE_BIT["float"]
    if DATE_RE.match(t):
        try:
            parse_date(t)
            return mask | TYPE_BIT["date"]
        except CastError:
            return mask
    if TS_RE.match(t):
        try:
            parse_timestamp(t)
            return mask | TYPE_BIT["timestamp"]
        except CastError:
            return mask
    return mask


def best_type(mask):
    for name in TYPE_ORDER:
        if mask & TYPE_BIT[name]:
            return name
    return "string"


# --------------------------------------------------------------------------
# Casting of natively typed values (JSONL / Parquet)
# --------------------------------------------------------------------------

def normalize_number(v):
    """JSON numbers: prefer int when integral and inside the int64 range."""
    if isinstance(v, float):
        if v.is_integer() and INT64_MIN <= v <= INT64_MAX:
            return int(v)
    return v


def _to_utc(dt):
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _dt_frac(dt):
    if dt.microsecond:
        return ("." + "%06d" % dt.microsecond).rstrip("0")
    return ""


def json_value_mask(v):
    """Inference mask for a natively typed JSONL value."""
    if isinstance(v, bool):
        return STR_BIT | TYPE_BIT["bool"]
    if isinstance(v, int):
        m = STR_BIT | TYPE_BIT["int"] | TYPE_BIT["float"]
        if v in (0, 1):
            m |= TYPE_BIT["bool"]
        return m
    if isinstance(v, float):
        return STR_BIT | TYPE_BIT["float"]
    if isinstance(v, str):
        # JSON strings carry no more type information than a CSV cell does,
        # which is why JSONL ranks equal to CSV for --schema-strategy.
        return value_mask(v)
    return STR_BIT


def cast_typed(v, typ):
    """Cast a natively typed value; returns (sort_value, output_text)."""
    if isinstance(v, str):
        return PARSERS[typ](v)
    if isinstance(v, bool):
        if typ == "bool":
            return (v, "true" if v else "false")
        if typ == "int":
            return (1, "1") if v else (0, "0")
        if typ == "float":
            f = 1.0 if v else 0.0
            return f, format_float(f)
        if typ == "string":
            s = "true" if v else "false"
            return s, s
        raise CastError(typ)
    if isinstance(v, int):
        if typ == "int":
            return v, str(v)
        if typ == "float":
            f = float(v)
            return f, format_float(f)
        if typ == "bool":
            if v == 0:
                return False, "false"
            if v == 1:
                return True, "true"
            raise CastError(typ)
        if typ == "string":
            s = str(v)
            return s, s
        raise CastError(typ)
    if isinstance(v, float):
        if typ == "float":
            return v, format_float(v)
        if typ == "int":
            if v.is_integer() and INT64_MIN <= v <= INT64_MAX:
                iv = int(v)
                return iv, str(iv)
            raise CastError(typ)
        if typ == "bool":
            if v == 0.0:
                return False, "false"
            if v == 1.0:
                return True, "true"
            raise CastError(typ)
        if typ == "string":
            s = format_float(v)
            return s, s
        raise CastError(typ)
    if isinstance(v, Decimal):
        if typ == "int":
            if v == v.to_integral_value():
                iv = int(v)
                return iv, str(iv)
            raise CastError(typ)
        if typ == "float":
            f = float(v)
            return f, format_float(f)
        if typ == "bool":
            if v == 0:
                return False, "false"
            if v == 1:
                return True, "true"
            raise CastError(typ)
        if typ == "string":
            s = str(v)
            return s, s
        raise CastError(typ)
    if isinstance(v, datetime):
        dt = _to_utc(v)
        if typ == "timestamp":
            return _ts_render(dt, _dt_frac(dt))
        if typ == "date":
            s = "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)
            return s, s
        if typ == "string":
            _k, s = _ts_render(dt, _dt_frac(dt))
            return s, s
        raise CastError(typ)
    if isinstance(v, _date):
        if typ == "date":
            s = "%04d-%02d-%02d" % (v.year, v.month, v.day)
            return s, s
        if typ == "timestamp":
            return _ts_render(datetime(v.year, v.month, v.day), "")
        if typ == "string":
            s = "%04d-%02d-%02d" % (v.year, v.month, v.day)
            return s, s
        raise CastError(typ)
    if isinstance(v, _time):
        if typ == "string":
            s = v.isoformat()
            return s, s
        raise CastError(typ)
    if isinstance(v, (bytes, bytearray)):
        return PARSERS[typ](bytes(v).decode("utf-8", "replace"))
    raise CastError(typ)


# --------------------------------------------------------------------------
# CSV reading / writing
# --------------------------------------------------------------------------

def split_line(line, quotechar, escapechar, delim=","):
    """Split a single RFC-4180 record into fields.

    Supports both doubled quotes ("") and backslash-style escapes (\").
    """
    if quotechar not in line and (escapechar is None or escapechar not in line):
        return line.split(delim)
    fields = []
    i = 0
    n = len(line)
    while True:
        buf = []
        if i < n and line[i] == quotechar:
            i += 1
            while i < n:
                c = line[i]
                if c == quotechar:
                    if i + 1 < n and line[i + 1] == quotechar:
                        buf.append(quotechar)
                        i += 2
                        continue
                    i += 1
                    break
                if (escapechar and c == escapechar and i + 1 < n
                        and line[i + 1] in (quotechar, escapechar, delim)):
                    buf.append(line[i + 1])
                    i += 2
                    continue
                buf.append(c)
                i += 1
            # Anything between the closing quote and the delimiter is kept.
            while i < n and line[i] != delim:
                buf.append(line[i])
                i += 1
        else:
            while i < n and line[i] != delim:
                c = line[i]
                if (escapechar and c == escapechar and i + 1 < n
                        and line[i + 1] in (quotechar, escapechar, delim)):
                    buf.append(line[i + 1])
                    i += 2
                    continue
                buf.append(c)
                i += 1
        fields.append("".join(buf))
        if i < n and line[i] == delim:
            i += 1
            continue
        break
    return fields


def make_encoder(quotechar):
    special = (",", quotechar, "\n", "\r")
    doubled = quotechar + quotechar

    def encode_field(value):
        for ch in special:
            if ch in value:
                return quotechar + value.replace(quotechar, doubled) + quotechar
        return value
    return encode_field


# --------------------------------------------------------------------------
# Hive-style partition segments
# --------------------------------------------------------------------------

# Characters that survive a partition value unescaped.  Everything else is
# percent-encoded, one "%XX" group per UTF-8 byte (space -> %20, / -> %2F).
_PART_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789._-")
_PART_ESCAPE = {b: ("%%%02X" % b) for b in range(256)}
for _b in range(256):
    if chr(_b) in _PART_SAFE:
        _PART_ESCAPE[_b] = chr(_b)
del _b

# Literal used for a null (or missing) partition value.
NULL_PARTITION = "_null"

PART_FILE_TEMPLATE = "part-%05d.csv"


def encode_partition_value(text):
    """Percent-encode the UTF-8 bytes of ``text`` outside [A-Za-z0-9._-]."""
    esc = _PART_ESCAPE
    return "".join([esc[b] for b in text.encode("utf-8")])


def partition_path(columns, values):
    """Build ``col=val/col=val`` from raw (already cast) partition values.

    ``None`` stands for a missing value and becomes ``_null``.
    """
    segs = []
    for name, value in zip(columns, values):
        if value is None:
            segs.append(name + "=" + NULL_PARTITION)
        else:
            segs.append(name + "=" + encode_partition_value(value))
    return "/".join(segs)


# --------------------------------------------------------------------------
# Input format / compression detection
# --------------------------------------------------------------------------

EXT_FORMAT = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

FORMAT_RANK = {"parquet": 0, "jsonl": 1, "csv": 1, "tsv": 2}


def _head_bytes(path, n):
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError as exc:
        die("cannot read %s: %s" % (path, exc.strerror or exc), EXIT_IO)


def _head_decompressed(path, comp, n):
    try:
        if comp == "gzip":
            with gzip.open(path, "rb") as fh:
                return fh.read(n)
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError as exc:
        die("cannot read %s: %s" % (path, exc.strerror or exc), EXIT_IO)
    except EOFError:
        die("truncated gzip stream: %s" % path, EXIT_DIALECT)
    except Exception as exc:  # zlib/gzip decoding problems
        die("cannot decompress %s: %s" % (path, exc), EXIT_DIALECT)


def detect_compression(path, forced):
    base = os.path.basename(path).lower()
    gz_ext = base.endswith(".gz")
    comp = ("gzip" if gz_ext else "none") if forced == "auto" else forced
    looks_gzip = _head_bytes(path, 2) == GZIP_MAGIC
    if comp == "gzip" and not looks_gzip:
        die("compression mismatch: %s is not gzip-compressed" % path, EXIT_DIALECT)
    if comp == "none" and looks_gzip:
        die("compression mismatch: %s is gzip-compressed" % path, EXIT_DIALECT)
    return comp


def detect_format(path, forced, comp):
    if forced != "auto":
        return forced
    base = os.path.basename(path).lower()
    if base.endswith(".gz"):
        base = base[:-3]
    ext = os.path.splitext(base)[1]
    fmt = EXT_FORMAT.get(ext)
    if fmt is not None:
        return fmt
    if _head_decompressed(path, comp, 4) == PARQUET_MAGIC:
        return "parquet"
    die("cannot determine input format for %s: unrecognised extension %r "
        "(use --input-format)" % (path, ext), EXIT_USAGE)


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

MISSING = object()


class Source:
    """A single input file, of one of the four supported formats."""

    def __init__(self, path, fmt, comp, opts):
        self.path = path
        self.fmt = fmt
        self.comp = comp
        self.opts = opts
        self.rank = FORMAT_RANK[fmt]
        self.typed = fmt in ("jsonl", "parquet")
        # ``header`` is the file's column list for positional formats and
        # ``None`` for JSONL, whose rows are yielded as dicts.  It is always
        # populated once iteration of ``rows()`` has started.
        self.header = None

    # -- text access -----------------------------------------------------
    def _text(self):
        try:
            if self.comp == "gzip":
                raw = gzip.open(self.path, "rb")
            else:
                raw = open(self.path, "rb")
        except OSError as exc:
            die("cannot read %s: %s" % (self.path, exc.strerror or exc), EXIT_IO)
        return io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")

    def _lines(self):
        stream = self._text()
        try:
            try:
                for lineno, raw in enumerate(stream, start=1):
                    line = raw.rstrip("\n")
                    if line.endswith("\r"):
                        line = line[:-1]
                    yield lineno, line
            except (OSError, EOFError) as exc:
                die("cannot read %s: %s" % (self.path, exc), EXIT_DIALECT)
            except UnicodeDecodeError as exc:
                die("%s is not valid UTF-8: %s" % (self.path, exc), EXIT_DIALECT)
        finally:
            stream.close()

    # -- schema ----------------------------------------------------------
    def schema_masks(self):
        """Declared column masks, or None when values must be scanned."""
        if self.fmt != "parquet":
            return None
        return self._parquet_schema()

    # -- rows ------------------------------------------------------------
    def rows(self):
        if self.fmt == "csv":
            return self._rows_csv()
        if self.fmt == "tsv":
            return self._rows_tsv()
        if self.fmt == "jsonl":
            return self._rows_jsonl()
        return self._rows_parquet()

    def _rows_csv(self):
        quotechar = self.opts["quotechar"]
        escapechar = self.opts["escapechar"]
        first = True
        for lineno, line in self._lines():
            if first:
                first = False
                self.header = split_line(line, quotechar, escapechar)
                continue
            if line == "":
                continue
            yield lineno, split_line(line, quotechar, escapechar)
        if first:
            self.header = []

    def _rows_tsv(self):
        first = True
        width = 0
        for lineno, line in self._lines():
            if first:
                first = False
                self.header = line.split("\t")
                width = len(self.header)
                continue
            if line == "":
                continue
            fields = line.split("\t")
            if len(fields) > width:
                die("%s line %d: literal tab inside a field is not allowed in "
                    "TSV (%d fields, header has %d)"
                    % (self.path, lineno, len(fields), width), EXIT_DIALECT)
            yield lineno, fields
        if first:
            die("%s: TSV input requires a header row" % self.path, EXIT_DIALECT)

    def _rows_jsonl(self):
        for lineno, line in self._lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                die("%s line %d: invalid JSON (%s)" % (self.path, lineno, exc),
                    EXIT_DIALECT)
            if isinstance(obj, list):
                die("%s line %d: nested structure (top-level array); JSONL "
                    "records must be flat objects" % (self.path, lineno),
                    EXIT_NESTED)
            if not isinstance(obj, dict):
                die("%s line %d: each JSONL record must be a JSON object"
                    % (self.path, lineno), EXIT_DIALECT)
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    die("%s line %d: nested structure for key %r; JSONL objects "
                        "must be flat" % (self.path, lineno, k), EXIT_NESTED)
                if type(v) is float:
                    obj[k] = normalize_number(v)
            yield lineno, obj

    # -- parquet ---------------------------------------------------------
    def _parquet_open(self):
        try:
            import pyarrow.parquet as pq  # noqa: F401
        except ImportError:
            die("reading Parquet requires the 'pyarrow' package "
                "(pip install -r requirements.txt)", EXIT_USAGE)
        import pyarrow.parquet as pq
        try:
            if self.comp == "gzip":
                handle = gzip.open(self.path, "rb")
            else:
                handle = open(self.path, "rb")
        except OSError as exc:
            die("cannot read %s: %s" % (self.path, exc.strerror or exc), EXIT_IO)
        try:
            pf = pq.ParquetFile(handle)
        except Exception as exc:
            handle.close()
            die("%s is not a readable Parquet file: %s" % (self.path, exc),
                EXIT_DIALECT)
        return pf, handle

    def _arrow_mask(self, field):
        import pyarrow.types as pat
        t = field.type
        if pat.is_dictionary(t):
            t = t.value_type
        if pat.is_nested(t):
            die("%s: column %r has nested type %s; Parquet inputs must have "
                "flat schemas" % (self.path, field.name, t), EXIT_NESTED)
        if pat.is_boolean(t):
            return STR_BIT | TYPE_BIT["bool"]
        if pat.is_integer(t):
            return STR_BIT | TYPE_BIT["int"] | TYPE_BIT["float"]
        if pat.is_floating(t) or pat.is_decimal(t):
            return STR_BIT | TYPE_BIT["float"]
        if pat.is_timestamp(t):
            return STR_BIT | TYPE_BIT["timestamp"]
        if pat.is_date(t):
            return STR_BIT | TYPE_BIT["date"]
        if pat.is_null(t):
            return ALL_BITS  # carries no information
        return STR_BIT

    def _parquet_schema(self):
        pf, handle = self._parquet_open()
        try:
            schema = pf.schema_arrow
            masks = {}
            names = []
            for field in schema:
                m = self._arrow_mask(field)
                if field.name not in masks:
                    masks[field.name] = m
                    names.append(field.name)
            self.header = list(schema.names)
            return masks
        finally:
            handle.close()

    def _parquet_batch_size(self, pf):
        # --parquet-row-group-bytes is advisory; never let it push a single
        # decoded batch past the memory budget.
        target = min(self.opts["parquet_row_group_bytes"],
                     max(1 << 20, self.opts["memory_budget_bytes"]))
        size = 8192
        try:
            md = pf.metadata
            if md is not None and md.num_rows > 0:
                total = 0
                for i in range(md.num_row_groups):
                    total += md.row_group(i).total_byte_size
                if total > 0:
                    avg = float(total) / float(md.num_rows)
                    size = int(target / max(avg, 1.0))
        except Exception:
            pass
        return max(1, min(size, 131072))

    def _rows_parquet(self):
        pf, handle = self._parquet_open()
        try:
            schema = pf.schema_arrow
            for field in schema:
                self._arrow_mask(field)  # re-validate flatness
            self.header = list(schema.names)
            ncols = len(self.header)
            batch_size = self._parquet_batch_size(pf)
            rowno = 0
            try:
                batches = pf.iter_batches(batch_size=batch_size)
            except Exception as exc:
                die("cannot read %s: %s" % (self.path, exc), EXIT_DIALECT)
            while True:
                try:
                    batch = next(batches)
                except StopIteration:
                    break
                except Exception as exc:
                    die("cannot read %s: %s" % (self.path, exc), EXIT_DIALECT)
                cols = [batch.column(i).to_pylist() for i in range(ncols)]
                for i in range(batch.num_rows):
                    rowno += 1
                    yield rowno, [cols[j][i] for j in range(ncols)]
        finally:
            handle.close()


def header_index(header, names):
    """Positions of ``names`` inside ``header`` (-1 when absent, first wins)."""
    pos = {}
    for i, c in enumerate(header):
        if c not in pos:
            pos[c] = i
    return [pos.get(c, -1) for c in names]


def unique_header(header):
    out, seen = [], set()
    for c in header:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

def load_schema(spec):
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
        except OSError as exc:
            die("cannot read schema %s: %s" % (spec, exc.strerror or exc), EXIT_IO)
    else:
        raw = spec
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        die("invalid schema JSON: %s" % exc)
    if not isinstance(data, dict) or "columns" not in data:
        die("schema must be an object containing a 'columns' array")
    cols = data["columns"]
    if not isinstance(cols, list) or not cols:
        die("schema 'columns' must be a non-empty array")
    names, types = [], []
    for entry in cols:
        if isinstance(entry, str):
            name, typ = entry, "string"
        elif isinstance(entry, dict):
            name = entry.get("name")
            typ = entry.get("type", "string")
        else:
            die("invalid schema column entry: %r" % (entry,))
        if not name or not isinstance(name, str):
            die("schema column is missing a valid 'name'")
        if typ not in VALID_TYPES:
            die("unknown type %r for column %r (valid: %s)"
                % (typ, name, ", ".join(sorted(VALID_TYPES))))
        if name in names:
            die("duplicate column %r in schema" % name)
        names.append(name)
        types.append(typ)
    return names, types


def resolve_type(obs, mode, strategy):
    """Pick a type for one column from ``[(rank, mask), ...]`` observations."""
    if not obs:
        return "string"
    if strategy == "union":
        m = ALL_BITS
        for _r, mask in obs:
            m &= mask
        return best_type(m)
    if strategy == "consensus":
        total = len(obs)
        for name in TYPE_ORDER:
            bit = TYPE_BIT[name]
            support = 0
            for _r, mask in obs:
                if mask & bit:
                    support += 1
            if support * 2 > total:
                return name
        return "string"
    # authoritative: only the most trustworthy sources get a vote
    top = min(r for r, _m in obs)
    sel = [mask for r, mask in obs if r == top]
    if mode == "loose":
        m = ALL_BITS
        for mask in sel:
            m &= mask
        return best_type(m)
    found = {best_type(mask) for mask in sel}
    if len(found) == 1:
        return found.pop()
    return "string"


def infer_schema(sources, mode, strategy, null_literal):
    """Return (column_names, column_types) inferred from every input."""
    names = []
    seen = set()
    obs = {}
    loose = mode == "loose"

    def note(col):
        if col not in seen:
            seen.add(col)
            names.append(col)

    for src in sources:
        declared = src.schema_masks()
        if declared is not None:
            for col, mask in declared.items():
                note(col)
                if mask != ALL_BITS:
                    obs.setdefault(col, []).append((src.rank, mask))
            continue

        masks = {}
        done = set()
        idx = None
        cols = None
        typed = src.typed
        for _loc, row in src.rows():
            if src.header is not None:
                if idx is None:
                    cols = unique_header(src.header)
                    idx = header_index(src.header, cols)
                nf = len(row)
                for ci, col in enumerate(cols):
                    if col in done:
                        continue
                    p = idx[ci]
                    raw = row[p] if 0 <= p < nf else ""
                    if loose and (raw == "" or (null_literal and raw == null_literal)):
                        continue
                    m = masks.get(col, ALL_BITS) & value_mask(raw)
                    masks[col] = m
                    if m == STR_BIT:
                        done.add(col)
            else:
                for col, v in row.items():
                    if v is None:
                        # An explicit JSON null is missing data, not a value.
                        masks.setdefault(col, ALL_BITS)
                        continue
                    if col in done:
                        continue
                    m = masks.get(col, ALL_BITS) & json_value_mask(v)
                    masks[col] = m
                    if m == STR_BIT:
                        done.add(col)
        if src.header is not None:
            for col in unique_header(src.header):
                note(col)
        for col in masks:
            note(col)
        for col, m in masks.items():
            if m != ALL_BITS:
                obs.setdefault(col, []).append((src.rank, m))

    names.sort()  # ascending lexicographic column order
    types = [resolve_type(obs.get(c, ()), mode, strategy) for c in names]
    return names, types


# --------------------------------------------------------------------------
# Sort keys
# --------------------------------------------------------------------------

NULL_RANK = 0
NUM_RANK = 1
STR_RANK = 2


def key_material(values, seq, desc):
    """Build a plain list that sorts correctly under ``sorted(..., reverse=desc)``.

    Each key column contributes a (rank, value) pair so that nulls always
    compare less than non-nulls (hence first ascending, last descending), and
    so that values of different kinds never compare against each other.  The
    trailing sequence number preserves input appearance order for equal keys
    in *both* directions.
    """
    out = []
    for v in values:
        if v is None:
            out.append(NULL_RANK)
            out.append(0)
        elif isinstance(v, str):
            out.append(STR_RANK)
            out.append(v)
        else:
            out.append(NUM_RANK)
            out.append(v)
    out.append(-seq if desc else seq)
    return out


# --------------------------------------------------------------------------
# External merge sort
# --------------------------------------------------------------------------

_first = operator.itemgetter(0)


class ExternalSorter:
    def __init__(self, desc, tmpdir, budget_bytes, max_records, fan_in=24):
        self.desc = bool(desc)
        self.tmpdir = tmpdir
        self.budget = budget_bytes
        self.max_records = max_records
        self.fan_in = fan_in
        self.buf = []
        self.size = 0
        self.runs = []
        self._n = 0

    def add(self, rec, approx_size):
        self.buf.append(rec)
        self.size += approx_size
        if self.size >= self.budget or len(self.buf) >= self.max_records:
            self._spill()

    def _new_run_path(self):
        self._n += 1
        return os.path.join(self.tmpdir, "run-%05d.jsonl" % self._n)

    def _spill(self):
        if not self.buf:
            return
        self.buf.sort(key=_first, reverse=self.desc)
        path = self._new_run_path()
        with open(path, "w", encoding="utf-8", newline="") as fh:
            for rec in self.buf:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")
        self.runs.append(path)
        self.buf = []
        self.size = 0

    @staticmethod
    def _read_run(path):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            for line in fh:
                if line:
                    yield json.loads(line)

    def _merge(self, paths):
        return heapq.merge(*[self._read_run(p) for p in paths], key=_first,
                          reverse=self.desc)

    def sorted_records(self):
        if not self.runs:
            self.buf.sort(key=_first, reverse=self.desc)
            return iter(self.buf)
        self._spill()
        paths = self.runs
        while len(paths) > self.fan_in:
            nxt = []
            for i in range(0, len(paths), self.fan_in):
                group = paths[i:i + self.fan_in]
                if len(group) == 1:
                    nxt.append(group[0])
                    continue
                dest = self._new_run_path()
                with open(dest, "w", encoding="utf-8", newline="") as fh:
                    for rec in self._merge(group):
                        fh.write(json.dumps(rec, ensure_ascii=False,
                                            separators=(",", ":")))
                        fh.write("\n")
                for p in group:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                nxt.append(dest)
            paths = nxt
        return self._merge(paths)


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def die(msg, code=EXIT_USAGE):
    sys.stderr.write("merge_files.py: error: %s\n" % msg)
    sys.exit(code)


def one_char(value, name):
    if value is None:
        return None
    if value in ("", "none", "None"):
        return None
    if len(value) != 1:
        die("%s must be a single character (got %r)" % (name, value))
    return value


def build_parser():
    p = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge CSV, TSV, JSON Lines and Parquet inputs into one "
                    "sorted CSV.")
    p.add_argument("--output", required=True,
                   help="output path, or '-' for stdout")
    p.add_argument("--key", required=True,
                   help="comma separated list of sort key columns")
    p.add_argument("--partition-by", dest="partition_by", default=None,
                   help="comma separated columns to Hive-partition the output by")
    p.add_argument("--max-rows-per-file", dest="max_rows_per_file", type=int,
                   default=None,
                   help="cut each output file after this many data rows")
    p.add_argument("--max-bytes-per-file", dest="max_bytes_per_file", type=int,
                   default=None,
                   help="cut each output file before it exceeds this many bytes")
    p.add_argument("--desc", action="store_true",
                   help="sort descending (applies to all keys)")
    p.add_argument("--schema", default=None,
                   help="path to a schema JSON file (or inline JSON)")
    p.add_argument("--infer", choices=("strict", "loose"), default="strict",
                   help="type inference mode when no schema is given")
    p.add_argument("--schema-strategy", dest="schema_strategy",
                   choices=("authoritative", "consensus", "union"),
                   default="authoritative",
                   help="how to reconcile conflicting types across inputs")
    p.add_argument("--on-type-error", dest="on_type_error",
                   choices=("coerce-null", "fail", "keep-string"),
                   default="coerce-null")
    p.add_argument("--memory-limit-mb", dest="memory_limit_mb", type=int,
                   default=256, help="approximate memory budget in MiB")
    p.add_argument("--temp-dir", dest="temp_dir", default=None,
                   help="directory for temporary spill files")
    p.add_argument("--csv-quotechar", dest="quotechar", default='"')
    p.add_argument("--csv-escapechar", dest="escapechar", default="\\")
    p.add_argument("--csv-null-literal", dest="null_literal", default="")
    p.add_argument("--input-format", dest="input_format",
                   choices=("auto", "csv", "tsv", "jsonl", "parquet"),
                   default="auto", help="force an input format for every input")
    p.add_argument("--compression", choices=("auto", "none", "gzip"),
                   default="auto", help="force input compression handling")
    p.add_argument("--parquet-row-group-bytes", dest="parquet_row_group_bytes",
                   type=int, default=64 * 1024 * 1024,
                   help="advisory Parquet batch size, in bytes")
    p.add_argument("inputs", nargs="+", metavar="INPUT")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    quotechar = one_char(args.quotechar, "--csv-quotechar") or '"'
    escapechar = one_char(args.escapechar, "--csv-escapechar")
    null_literal = args.null_literal

    if args.parquet_row_group_bytes is not None and args.parquet_row_group_bytes <= 0:
        die("--parquet-row-group-bytes must be positive")

    max_rows_per_file = args.max_rows_per_file
    max_bytes_per_file = args.max_bytes_per_file
    if max_rows_per_file is not None and max_rows_per_file <= 0:
        die("--max-rows-per-file must be positive")
    if max_bytes_per_file is not None and max_bytes_per_file <= 0:
        die("--max-bytes-per-file must be positive")

    part_cols = []
    if args.partition_by is not None:
        part_cols = [c.strip() for c in args.partition_by.split(",")]
        if not part_cols or any(c == "" for c in part_cols):
            die("--partition-by must name at least one column")
        seen = set()
        for c in part_cols:
            if c in seen:
                die("--partition-by names %r more than once" % c)
            seen.add(c)

    partitioned = bool(part_cols) or (max_rows_per_file is not None) or \
        (max_bytes_per_file is not None)
    if partitioned and args.output == "-":
        die("--output must be a directory path (not '-') when "
            "--partition-by, --max-rows-per-file or --max-bytes-per-file "
            "is used")

    opts = {
        "quotechar": quotechar,
        "escapechar": escapechar,
        "null_literal": null_literal,
        "parquet_row_group_bytes": args.parquet_row_group_bytes,
        # filled in once --memory-limit-mb has been validated
        "memory_budget_bytes": 1 << 20,
    }

    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        die("--memory-limit-mb must be positive")
    limit_mb = args.memory_limit_mb or 256
    # Python objects cost several times their serialized size; keep a wide
    # margin so we stay comfortably under the requested ceiling.
    budget = max(256 * 1024, (limit_mb * 1024 * 1024) // 16)
    max_records = max(1000, budget // 48)
    opts["memory_budget_bytes"] = budget

    inputs = list(args.inputs)
    for path in inputs:
        if not os.path.isfile(path):
            die("input file not found: %s" % path, EXIT_IO)

    sources = []
    for path in inputs:
        comp = detect_compression(path, args.compression)
        fmt = detect_format(path, args.input_format, comp)
        sources.append(Source(path, fmt, comp, opts))

    keys = [k.strip() for k in args.key.split(",")]
    if not keys or any(k == "" for k in keys):
        die("--key must name at least one column")

    if args.schema:
        names, types = load_schema(args.schema)
    else:
        names, types = infer_schema(sources, args.infer, args.schema_strategy,
                                    null_literal)

    if not names:
        die("no columns could be resolved from the inputs")

    col_index = {c: i for i, c in enumerate(names)}
    for k in keys:
        if k not in col_index:
            die("key column %r is not present in the resolved schema (%s)"
                % (k, ", ".join(names)), EXIT_KEY)
    key_positions = [col_index[k] for k in keys]

    for c in part_cols:
        if c not in col_index:
            die("partition column %r is not present in the resolved schema (%s)"
                % (c, ", ".join(names)), EXIT_KEY)
    part_positions = [col_index[c] for c in part_cols]

    tmp_parent = args.temp_dir
    if tmp_parent:
        os.makedirs(tmp_parent, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="merge_files-", dir=tmp_parent)

    def cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)

    atexit.register(cleanup)

    try:
        records = collect_records(sources, names, types, key_positions,
                                  null_literal, args.on_type_error, args.desc,
                                  tmpdir, budget, max_records,
                                  part_cols, part_positions)
        if partitioned:
            emit_partitioned(records, names, args.output, quotechar,
                             bool(part_cols), max_rows_per_file,
                             max_bytes_per_file)
        else:
            emit(records, names, args.output, quotechar)
    finally:
        cleanup()
        try:
            atexit.unregister(cleanup)
        except Exception:
            pass
    return EXIT_OK


def collect_records(sources, names, types, key_positions, null_literal,
                    on_type_error, desc, tmpdir, budget, max_records,
                    part_cols=(), part_positions=()):
    """Sort every input row.

    Yields ``[sort_key, row]`` pairs in output order.  When partition columns
    are given the sort key is prefixed with the row's Hive-style partition
    path, so rows of one partition come out contiguously and sorted by
    ``--key`` within the partition.
    """
    sorter = ExternalSorter(desc, tmpdir, budget, max_records)
    parsers = [PARSERS[t] for t in types]
    ncols = len(names)
    key_slot = {pos: i for i, pos in enumerate(key_positions)}
    nkeys = len(key_positions)
    part_cols = list(part_cols)
    part_slot = {pos: i for i, pos in enumerate(part_positions)}
    npart = len(part_cols)
    seq = 0

    for src in sources:
        typed = src.typed
        idx = None
        for loc, raw_row in src.rows():
            if src.header is not None:
                if idx is None:
                    idx = header_index(src.header, names)
                nf = len(raw_row)
                cells = [raw_row[idx[c]] if 0 <= idx[c] < nf else MISSING
                         for c in range(ncols)]
            else:
                cells = [raw_row.get(names[c], MISSING) for c in range(ncols)]

            row = [null_literal] * ncols
            keyvals = [None] * nkeys
            partvals = [None] * npart
            approx = 32
            for ci in range(ncols):
                v = cells[ci]
                if v is MISSING or v is None:
                    value, text = None, null_literal
                elif typed:
                    try:
                        value, text = cast_typed(v, types[ci])
                    except CastError:
                        value, text = _on_error(on_type_error, v, types[ci],
                                                names[ci], src.path, loc,
                                                null_literal, True)
                else:
                    if v == "" or (null_literal and v == null_literal):
                        value, text = None, null_literal
                    else:
                        try:
                            value, text = parsers[ci](v)
                        except CastError:
                            value, text = _on_error(on_type_error, v, types[ci],
                                                    names[ci], src.path, loc,
                                                    null_literal, False)
                row[ci] = text
                approx += len(text) + 8
                slot = key_slot.get(ci)
                if slot is not None:
                    keyvals[slot] = value
                    approx += 16
                if npart:
                    slot = part_slot.get(ci)
                    if slot is not None:
                        partvals[slot] = None if value is None else text
            sortkey = key_material(keyvals, seq, desc)
            if npart:
                path = partition_path(part_cols, partvals)
                sortkey.insert(0, path)
                approx += len(path) + 8
            sorter.add([sortkey, row], approx)
            seq += 1

    return sorter.sorted_records()


def _on_error(mode, value, typ, column, path, loc, null_literal, typed):
    if mode == "fail":
        sys.stderr.write(
            "merge_files.py: error: cannot cast %r to %s for column %r "
            "(%s line %d)\n" % (value, typ, column, path, loc))
        sys.exit(EXIT_TYPE)
    if mode == "keep-string":
        if typed:
            try:
                return cast_typed(value, "string")
            except CastError:
                s = str(value)
                return s, s
        return value, value
    return None, null_literal  # coerce-null


def emit(records, names, output, quotechar):
    encode = make_encoder(quotechar)

    def write_all(stream):
        write = stream.write
        write(",".join(encode(c) for c in names))
        write("\n")
        for rec in records:
            write(",".join(encode(c) for c in rec[1]))
            write("\n")
        stream.flush()

    if output == "-":
        stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  newline="", write_through=True)
        try:
            write_all(stream)
        finally:
            try:
                stream.detach()
            except Exception:
                pass
        return

    parent = os.path.dirname(os.path.abspath(output))
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            die("cannot create %s: %s" % (parent, exc.strerror or exc), EXIT_IO)
    try:
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".merge_files-",
                                   suffix=".tmp")
    except OSError as exc:
        die("cannot write %s: %s" % (output, exc.strerror or exc), EXIT_IO)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            write_all(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, output)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Partitioned output
# --------------------------------------------------------------------------

class PartFileWriter:
    """Writes ``part-00000.csv``, ``part-00001.csv``, ... into one directory.

    Every file starts with the resolved-schema header.  A new file is started
    as soon as appending a row would break ``max_rows`` or ``max_bytes``; a
    row that does not fit into an empty file is written anyway, on its own.
    """

    def __init__(self, directory, header, max_rows, max_bytes):
        self.directory = directory
        self.header = header
        self.header_bytes = len(header.encode("utf-8")) + 1
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.index = 0
        self.fh = None
        self.size = 0
        self.rows = 0

    def _open(self):
        path = os.path.join(self.directory, PART_FILE_TEMPLATE % self.index)
        self.index += 1
        self.fh = open(path, "w", encoding="utf-8", newline="")
        self.fh.write(self.header)
        self.fh.write("\n")
        self.size = self.header_bytes
        self.rows = 0

    def _close_file(self):
        if self.fh is None:
            return
        fh, self.fh = self.fh, None
        with fh:
            fh.flush()
            os.fsync(fh.fileno())

    def write(self, line):
        nbytes = len(line.encode("utf-8")) + 1
        if self.fh is None:
            self._open()
        elif self.rows and (
                (self.max_rows is not None and self.rows + 1 > self.max_rows)
                or (self.max_bytes is not None
                    and self.size + nbytes > self.max_bytes)):
            self._close_file()
            self._open()
        self.fh.write(line)
        self.fh.write("\n")
        self.size += nbytes
        self.rows += 1

    def ensure_started(self):
        """Emit a header-only first file even when no row was written."""
        if self.fh is None and self.index == 0:
            self._open()

    def close(self):
        self._close_file()


def _dir_mode():
    mask = os.umask(0)
    os.umask(mask)
    return 0o777 & ~mask


def _install_directory(tmpdir, dest):
    """Move ``tmpdir`` into place as ``dest``, replacing any previous tree."""
    try:
        os.chmod(tmpdir, _dir_mode())
    except OSError:
        pass
    if not os.path.exists(dest):
        os.rename(tmpdir, dest)
        return
    backup = tempfile.mkdtemp(dir=os.path.dirname(dest) or ".",
                              prefix="." + os.path.basename(dest) + ".old-")
    os.rmdir(backup)
    os.rename(dest, backup)
    try:
        os.rename(tmpdir, dest)
    except BaseException:
        os.rename(backup, dest)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def emit_partitioned(records, names, output, quotechar, has_fields,
                     max_rows, max_bytes):
    """Write a directory of CSV parts, atomically.

    Everything is built inside a sibling temporary directory which is renamed
    onto ``output`` once the last row has been written; any failure removes
    the temporary tree and leaves no partial output behind.
    """
    encode = make_encoder(quotechar)
    header = ",".join(encode(c) for c in names)

    dest = os.path.abspath(output)
    parent = os.path.dirname(dest) or "."
    if os.path.exists(dest) and not os.path.isdir(dest):
        die("--output %s exists and is not a directory" % output, EXIT_IO)
    try:
        os.makedirs(parent, exist_ok=True)
        tmpdir = tempfile.mkdtemp(
            dir=parent, prefix="." + os.path.basename(dest) + ".tmp-")
    except OSError as exc:
        die("cannot write %s: %s" % (output, exc.strerror or exc), EXIT_IO)

    try:
        writer = None
        current = None
        for rec in records:
            sortkey, row = rec[0], rec[1]
            reldir = sortkey[0] if has_fields else ""
            if writer is None or reldir != current:
                if writer is not None:
                    writer.close()
                target = (os.path.join(tmpdir, *reldir.split("/"))
                          if reldir else tmpdir)
                os.makedirs(target, exist_ok=True)
                writer = PartFileWriter(target, header, max_rows, max_bytes)
                current = reldir
            writer.write(",".join(encode(c) for c in row))
        if writer is None:
            # No rows at all: a plain shard run still yields one empty CSV,
            # while a field-partitioned run yields no partition directories.
            if not has_fields:
                writer = PartFileWriter(tmpdir, header, max_rows, max_bytes)
                writer.ensure_started()
        if writer is not None:
            writer.close()
        _install_directory(tmpdir, dest)
    except OSError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        die("cannot write %s: %s" % (output, exc.strerror or exc), EXIT_IO)
    except BaseException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.exit(EXIT_OK)
    except KeyboardInterrupt:
        sys.exit(130)

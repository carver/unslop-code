#!/usr/bin/env python3
"""
CSV Merger and Sorter.

Ingests multiple CSV files, aligns their schemas (provided or inferred),
casts cells to the resolved types and emits a single globally-sorted CSV.

Sorting is done with an external merge sort so that inputs far larger than
``--memory-limit-mb`` can be processed. All temporary resources are removed
on exit.
"""

from __future__ import annotations

import argparse
import atexit
import heapq
import io
import json
import operator
import os
import re
import shutil
import sys
import tempfile
from datetime import date as _date, datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------

# Highest priority first: timestamp > date > bool > int > float > string
TYPE_ORDER = ("timestamp", "date", "bool", "int", "float", "string")
TYPE_BIT = {name: 1 << i for i, name in enumerate(TYPE_ORDER)}
ALL_BITS = (1 << len(TYPE_ORDER)) - 1
VALID_TYPES = frozenset(TYPE_ORDER)

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


def parse_timestamp(text):
    dt, frac = _parse_ts_parts(text)
    base = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    out = base + frac + "Z"
    # Sort key: fixed-width fraction so lexicographic order is chronological.
    digits = (frac[1:] if frac else "")
    key = base + "." + (digits + "000000000")[:9]
    return key, out


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
    mask = TYPE_BIT["string"]
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


def iter_csv(path, quotechar, escapechar):
    """Yield (line_number, fields) for every data row; header yielded first."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if line.endswith("\r"):
                line = line[:-1]
            if lineno == 1:
                yield lineno, split_line(line, quotechar, escapechar)
                continue
            if line == "":
                continue
            yield lineno, split_line(line, quotechar, escapechar)


def read_header(path, quotechar, escapechar):
    for _lineno, fields in iter_csv(path, quotechar, escapechar):
        return fields
    return []


_QUOTE_NEEDED = (",", '"', "\n", "\r")


def encode_field(value):
    for ch in _QUOTE_NEEDED:
        if ch in value:
            return '"' + value.replace('"', '""') + '"'
    return value


def write_row(out, row):
    out.write(",".join(encode_field(c) for c in row))
    out.write("\n")


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

def load_schema(spec):
    if os.path.exists(spec):
        with open(spec, "r", encoding="utf-8-sig") as fh:
            raw = fh.read()
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


def infer_schema(paths, mode, quotechar, escapechar, null_literal):
    """Return (column_names, column_types) inferred from the inputs."""
    names = []
    seen = set()
    headers = {}
    for path in paths:
        header = read_header(path, quotechar, escapechar)
        hdr = []
        local = set()
        for col in header:
            if col in local:
                hdr.append(None)  # duplicate column in one file: ignore later ones
                continue
            local.add(col)
            hdr.append(col)
            if col not in seen:
                seen.add(col)
                names.append(col)
        headers[path] = hdr

    names.sort()  # ascending lexicographic column order

    # strict: per-file types, conflicts collapse to string
    # loose:  one global mask over all non-null values
    per_file = {c: [] for c in names}
    global_mask = {c: ALL_BITS for c in names}
    observed = {c: False for c in names}

    for path in paths:
        hdr = headers[path]
        idx = {c: i for i, c in enumerate(hdr) if c is not None}
        cols_here = [c for c in names if c in idx]
        if not cols_here:
            continue
        file_mask = {c: ALL_BITS for c in cols_here}
        file_seen = {c: False for c in cols_here}
        active = [(c, idx[c]) for c in cols_here]
        string_only = TYPE_BIT["string"]
        loose = mode == "loose"
        first = True
        for _lineno, fields in iter_csv(path, quotechar, escapechar):
            if first:
                first = False
                continue
            if not active:
                break
            nfields = len(fields)
            collapsed = False
            for col, i in active:
                raw = fields[i] if i < nfields else ""
                if loose and (raw == "" or (null_literal and raw == null_literal)):
                    continue
                m = file_mask[col] & value_mask(raw)
                file_mask[col] = m
                file_seen[col] = True
                if m == string_only:
                    collapsed = True
            if collapsed:
                # Nothing further can change a column that is already 'string'.
                active = [(c, i) for (c, i) in active
                          if file_mask[c] != string_only]
        for col in cols_here:
            if not file_seen[col]:
                continue
            observed[col] = True
            if loose:
                global_mask[col] &= file_mask[col]
            else:
                per_file[col].append(best_type(file_mask[col]))

    types = []
    for col in names:
        if not observed[col]:
            types.append("string")
        elif mode == "strict":
            found = set(per_file[col])
            types.append(found.pop() if len(found) == 1 else "string")
        else:
            types.append(best_type(global_mask[col]))
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

def die(msg, code=2):
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
        description="Merge multiple CSV files into one sorted CSV.")
    p.add_argument("--output", required=True,
                   help="output path, or '-' for stdout")
    p.add_argument("--key", required=True,
                   help="comma separated list of sort key columns")
    p.add_argument("--desc", action="store_true",
                   help="sort descending (applies to all keys)")
    p.add_argument("--schema", default=None,
                   help="path to a schema JSON file (or inline JSON)")
    p.add_argument("--infer", choices=("strict", "loose"), default="strict",
                   help="type inference mode when no schema is given")
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
    p.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    quotechar = one_char(args.quotechar, "--csv-quotechar") or '"'
    escapechar = one_char(args.escapechar, "--csv-escapechar")
    null_literal = args.null_literal

    inputs = list(args.inputs)
    for path in inputs:
        if not os.path.isfile(path):
            die("input file not found: %s" % path)

    keys = [k for k in args.key.split(",")]
    keys = [k.strip() for k in keys]
    if not keys or any(k == "" for k in keys):
        die("--key must name at least one column")

    if args.schema:
        names, types = load_schema(args.schema)
    else:
        names, types = infer_schema(inputs, args.infer, quotechar, escapechar,
                                    null_literal)

    if not names:
        die("no columns could be resolved from the inputs")

    col_index = {c: i for i, c in enumerate(names)}
    for k in keys:
        if k not in col_index:
            die("key column %r is not present in the resolved schema (%s)"
                % (k, ", ".join(names)))
    key_positions = [col_index[k] for k in keys]

    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        die("--memory-limit-mb must be positive")
    limit_mb = args.memory_limit_mb or 256
    # Python objects cost several times their serialized size; keep a wide
    # margin so we stay comfortably under the requested ceiling.
    budget = max(256 * 1024, (limit_mb * 1024 * 1024) // 16)
    max_records = max(1000, budget // 48)

    tmp_parent = args.temp_dir
    if tmp_parent:
        os.makedirs(tmp_parent, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="merge_files-", dir=tmp_parent)

    def cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)

    atexit.register(cleanup)

    try:
        records = collect_records(inputs, names, types, key_positions,
                                  quotechar, escapechar, null_literal,
                                  args.on_type_error, args.desc,
                                  tmpdir, budget, max_records)
        emit(records, names, null_literal, args.output)
    finally:
        cleanup()
        try:
            atexit.unregister(cleanup)
        except Exception:
            pass
    return 0


def collect_records(inputs, names, types, key_positions, quotechar, escapechar,
                    null_literal, on_type_error, desc, tmpdir, budget,
                    max_records):
    sorter = ExternalSorter(desc, tmpdir, budget, max_records)
    parsers = [PARSERS[t] for t in types]
    ncols = len(names)
    key_slot = {pos: i for i, pos in enumerate(key_positions)}
    nkeys = len(key_positions)
    seq = 0

    for path in inputs:
        header = None
        idx = None
        for lineno, fields in iter_csv(path, quotechar, escapechar):
            if header is None:
                header = fields
                seen = set()
                pos = {}
                for i, c in enumerate(header):
                    if c not in seen:
                        seen.add(c)
                        pos[c] = i
                idx = [pos.get(c, -1) for c in names]
                continue

            row = [null_literal] * ncols
            keyvals = [None] * nkeys
            approx = 32
            for ci in range(ncols):
                src = idx[ci]
                raw = fields[src] if 0 <= src < len(fields) else ""
                if raw == "" or (null_literal and raw == null_literal):
                    value = None
                    text = null_literal
                else:
                    try:
                        value, text = parsers[ci](raw)
                    except CastError:
                        if on_type_error == "fail":
                            sys.stderr.write(
                                "merge_files.py: error: cannot cast %r to %s "
                                "for column %r (%s line %d)\n"
                                % (raw, types[ci], names[ci], path, lineno))
                            sys.exit(1)
                        elif on_type_error == "keep-string":
                            value, text = raw, raw
                        else:  # coerce-null
                            value, text = None, null_literal
                row[ci] = text
                approx += len(text) + 8
                slot = key_slot.get(ci)
                if slot is not None:
                    keyvals[slot] = value
                    approx += 16
            sorter.add([key_material(keyvals, seq, desc), row], approx)
            seq += 1

    return sorter.sorted_records()


def emit(records, names, null_literal, output):
    if output == "-":
        stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  newline="", write_through=True)
        close = False
    else:
        parent = os.path.dirname(os.path.abspath(output))
        if parent:
            os.makedirs(parent, exist_ok=True)
        stream = open(output, "w", encoding="utf-8", newline="")
        close = True
    try:
        write_row(stream, names)
        for rec in records:
            write_row(stream, rec[1])
        stream.flush()
    finally:
        if close:
            stream.close()
        else:
            try:
                stream.detach()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)

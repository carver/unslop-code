#!/usr/bin/env python3
"""Merge multiple CSV files into one schema-aligned, globally sorted CSV.

The tool is streaming and uses an external (on-disk) merge sort so that inputs
much larger than ``--memory-limit-mb`` can be processed.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date as _date, datetime, timezone

UTC = timezone.utc

# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------

M_TS, M_DATE, M_BOOL, M_INT, M_FLOAT, M_STR = 1, 2, 4, 8, 16, 32
M_ALL = M_TS | M_DATE | M_BOOL | M_INT | M_FLOAT | M_STR

# Priority: timestamp > date > bool > int > float > string
TYPE_PRIORITY = (
    (M_TS, "timestamp"),
    (M_DATE, "date"),
    (M_BOOL, "bool"),
    (M_INT, "int"),
    (M_FLOAT, "float"),
    (M_STR, "string"),
)
VALID_TYPES = {name for _, name in TYPE_PRIORITY}
MASK_OF = {name: mask for mask, name in TYPE_PRIORITY}

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A timestamp *for inference purposes* must carry a time component, otherwise a
# plain ``YYYY-MM-DD`` column would be promoted to ``timestamp`` by priority.
TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?"
    r"(?:[Zz]|[+-]\d{2}:?\d{2}(?::\d{2})?)?$"
)


def pick_type(mask: int) -> str:
    for m, name in TYPE_PRIORITY:
        if mask & m:
            return name
    return "string"


# --------------------------------------------------------------------------
# Casting
# --------------------------------------------------------------------------


def _cast_string(raw: str):
    return (raw, raw)


def _cast_int(raw: str):
    s = raw.strip()
    if INT_RE.match(s):
        v = int(s)
        return (str(v), v)
    return None


def _cast_float(raw: str):
    s = raw.strip()
    if FLOAT_RE.match(s):
        v = float(s)
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return (repr(v), v)
    return None


def _cast_bool(raw: str):
    s = raw.strip().lower()
    if s in ("true", "1"):
        return ("true", 1)
    if s in ("false", "0"):
        return ("false", 0)
    return None


def _cast_date(raw: str):
    s = raw.strip()
    if DATE_RE.match(s):
        try:
            d = _date.fromisoformat(s)
        except ValueError:
            return None
        return (d.isoformat(), d.toordinal())
    return None


def _parse_iso_datetime(s: str):
    """Parse an ISO-8601 date or date-time.  Returns a datetime or None."""
    s = s.strip()
    if not s:
        return None
    t = s
    if t[-1] in ("z", "Z"):
        t = t[:-1] + "+00:00"
    t = t.replace(",", ".", 1) if ("," in t and "." not in t) else t
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y%m%dT%H%M%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def _format_ts(dt: datetime) -> str:
    out = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
    )
    if dt.microsecond:
        out += ".%06d" % dt.microsecond
    return out + "Z"


def _cast_timestamp(raw: str):
    dt = _parse_iso_datetime(raw)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return (_format_ts(dt), dt.timestamp())


CASTERS = {
    "string": _cast_string,
    "int": _cast_int,
    "float": _cast_float,
    "bool": _cast_bool,
    "date": _cast_date,
    "timestamp": _cast_timestamp,
}


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------


def value_candidates(raw: str) -> int:
    """Bit mask of the types a single non-null cell could be parsed as."""
    mask = M_STR
    s = raw.strip()
    if not s:
        return mask
    c0 = s[0]
    if c0.isdigit() or c0 in "+-.":
        if INT_RE.match(s):
            mask |= M_INT | M_FLOAT
            if s in ("0", "1"):
                mask |= M_BOOL
        elif FLOAT_RE.match(s):
            mask |= M_FLOAT
        if DATE_RE.match(s):
            if _cast_date(s) is not None:
                mask |= M_DATE
        elif TS_RE.match(s):
            if _cast_timestamp(s) is not None:
                mask |= M_TS
    else:
        low = s.lower()
        if low in ("true", "false"):
            mask |= M_BOOL
    return mask


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class UserError(Exception):
    pass


# --------------------------------------------------------------------------
# CSV helpers
# --------------------------------------------------------------------------


def reader_kwargs(args):
    kw = {
        "delimiter": ",",
        "quotechar": args.csv_quotechar,
    }
    if args.csv_escapechar is not None:
        kw["doublequote"] = False
        kw["escapechar"] = args.csv_escapechar
    else:
        kw["doublequote"] = True
    return kw


def writer_kwargs(args):
    kw = dict(reader_kwargs(args))
    kw["lineterminator"] = "\n"
    kw["quoting"] = csv.QUOTE_MINIMAL
    return kw


def open_input(path):
    return open(path, "r", encoding="utf-8-sig", newline="")


def read_header(path, args):
    with open_input(path) as fh:
        rd = csv.reader(fh, **reader_kwargs(args))
        for row in rd:
            return row
    return None


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------


def load_schema(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise UserError("cannot read schema file %r: %s" % (path, exc))
    except ValueError as exc:
        raise UserError("invalid JSON in schema file %r: %s" % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
        raise UserError("schema file must be an object with a 'columns' array")
    columns = []
    for i, col in enumerate(data["columns"]):
        if not isinstance(col, dict) or "name" not in col:
            raise UserError("schema column #%d must be an object with a 'name'" % (i + 1))
        name = col["name"]
        typ = col.get("type", "string")
        if not isinstance(name, str) or not isinstance(typ, str):
            raise UserError("schema column #%d has a non-string name/type" % (i + 1))
        if typ not in VALID_TYPES:
            raise UserError(
                "schema column %r has unknown type %r (valid: %s)"
                % (name, typ, ", ".join(sorted(VALID_TYPES)))
            )
        columns.append((name, typ))
    if not columns:
        raise UserError("schema file declares no columns")
    return columns


def infer_schema(inputs, args, null_literal):
    """Return [(name, type), ...] inferred from the union of the input headers."""
    names = []
    seen_names = set()
    headers = {}
    for path in inputs:
        header = read_header(path, args)
        if header is None:
            header = []
        headers[path] = header
        for name in header:
            if name not in seen_names:
                seen_names.add(name)
                names.append(name)

    order = sorted(names)
    if not order:
        return []

    rkw = reader_kwargs(args)
    loose = args.infer == "loose"

    # global (loose) accumulators
    g_mask = {n: M_ALL for n in order}
    g_seen = {n: False for n in order}
    # strict accumulators: per-column set of per-file types
    per_col_types = {n: set() for n in order}

    for path in inputs:
        header = headers[path]
        idx = {}
        for pos, name in enumerate(header):
            if name not in idx:
                idx[name] = pos
        cols = [(name, pos) for name, pos in idx.items()]
        if not cols:
            continue
        f_mask = {name: M_ALL for name, _ in cols}
        f_seen = {name: False for name, _ in cols}
        with open_input(path) as fh:
            rd = csv.reader(fh, **rkw)
            try:
                next(rd)
            except StopIteration:
                continue
            for row in rd:
                if not row:
                    continue
                n = len(row)
                for name, pos in cols:
                    if pos >= n:
                        continue
                    raw = row[pos]
                    if raw is None or raw == "" or (null_literal and raw == null_literal):
                        continue
                    if not f_seen[name]:
                        f_seen[name] = True
                    f_mask[name] &= value_candidates(raw)
        for name, _ in cols:
            if f_seen[name]:
                g_seen[name] = True
                g_mask[name] &= f_mask[name]
                per_col_types[name].add(pick_type(f_mask[name]))

    resolved = []
    for name in order:
        if not g_seen[name]:
            resolved.append((name, "string"))
            continue
        if loose:
            resolved.append((name, pick_type(g_mask[name])))
        else:
            types = per_col_types[name]
            resolved.append((name, types.pop() if len(types) == 1 else "string"))
    return resolved


# --------------------------------------------------------------------------
# Record production
# --------------------------------------------------------------------------

NULL_KEY = [0]


def iter_records(inputs, columns, key_positions, args, null_literal):
    """Yield ``[keylist, seq, rendered_row]`` for every input row, in input order."""
    names = [c[0] for c in columns]
    types = [c[1] for c in columns]
    casters = [CASTERS[t] for t in types]
    ncols = len(columns)
    key_set = set(key_positions)
    on_err = args.on_type_error
    rkw = reader_kwargs(args)
    seq = 0

    for path in inputs:
        with open_input(path) as fh:
            rd = csv.reader(fh, **rkw)
            try:
                header = next(rd)
            except StopIteration:
                continue
            pos_of = {}
            for pos, name in enumerate(header):
                if name not in pos_of:
                    pos_of[name] = pos
            idx = [pos_of.get(name, -1) for name in names]
            lineno = 1
            for row in rd:
                lineno += 1
                if not row:
                    continue
                rlen = len(row)
                rendered = [None] * ncols
                keys = {}
                for c in range(ncols):
                    p = idx[c]
                    raw = row[p] if 0 <= p < rlen else None
                    if raw is None or raw == "" or (null_literal and raw == null_literal):
                        rendered[c] = null_literal
                        if c in key_set:
                            keys[c] = NULL_KEY
                        continue
                    res = casters[c](raw)
                    if res is None:
                        if on_err == "fail":
                            raise UserError(
                                "cannot cast %r to type %r for column %r "
                                "(file %s, line %d)" % (raw, types[c], names[c], path, lineno)
                            )
                        if on_err == "keep-string":
                            rendered[c] = raw
                            if c in key_set:
                                keys[c] = [1, 1, raw]
                            continue
                        rendered[c] = null_literal
                        if c in key_set:
                            keys[c] = NULL_KEY
                        continue
                    rendered[c] = res[0]
                    if c in key_set:
                        keys[c] = [1, 0, res[1]]
                yield [[keys[c] for c in key_positions], seq, rendered]
                seq += 1


# --------------------------------------------------------------------------
# External sort
# --------------------------------------------------------------------------


def _key_asc(rec):
    return (rec[0], rec[1])


def _key_desc(rec):
    return (rec[0], -rec[1])


MAX_FANIN = 128


def estimate_size(rec):
    """Rough in-memory footprint of a buffered record, in bytes."""
    total = 200 + 200 * len(rec[0])
    for v in rec[2]:
        total += 60 + (len(v) if v else 0)
    return total


def _run_reader(fh):
    for line in fh:
        if line:
            yield json.loads(line)


def _write_run(records, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


class _Sorter:
    """External merge sort with a bounded merge fan-in."""

    def __init__(self, desc, budget_bytes, tmpdir):
        self.desc = desc
        self.keyfn = _key_desc if desc else _key_asc
        self.budget = budget_bytes
        self.tmpdir = tmpdir
        self.runs = []
        self.handles = []
        self._counter = 0

    def _new_path(self):
        self._counter += 1
        return os.path.join(self.tmpdir, "run_%06d.jsonl" % self._counter)

    def _open(self, path):
        fh = open(path, "r", encoding="utf-8", newline="")
        self.handles.append(fh)
        return _run_reader(fh)

    def _merge(self, paths):
        return heapq.merge(*(self._open(p) for p in paths),
                           key=self.keyfn, reverse=self.desc)

    def close(self):
        for fh in self.handles:
            try:
                fh.close()
            except OSError:
                pass
        self.handles = []

    def sort(self, records):
        buf = []
        used = 0
        for rec in records:
            buf.append(rec)
            used += estimate_size(rec)
            if used >= self.budget:
                buf.sort(key=self.keyfn, reverse=self.desc)
                path = self._new_path()
                _write_run(buf, path)
                self.runs.append(path)
                buf = []
                used = 0

        if not self.runs:
            buf.sort(key=self.keyfn, reverse=self.desc)
            return iter(buf)

        if buf:
            buf.sort(key=self.keyfn, reverse=self.desc)
            path = self._new_path()
            _write_run(buf, path)
            self.runs.append(path)
            buf = []

        # Bound the number of simultaneously open run files.
        runs = self.runs
        while len(runs) > MAX_FANIN:
            merged_runs = []
            for i in range(0, len(runs), MAX_FANIN):
                group = runs[i:i + MAX_FANIN]
                if len(group) == 1:
                    merged_runs.append(group[0])
                    continue
                path = self._new_path()
                _write_run(self._merge(group), path)
                self.close()
                for old in group:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
                merged_runs.append(path)
            runs = merged_runs
        return self._merge(runs)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def one_char(value):
    if len(value) != 1:
        raise argparse.ArgumentTypeError("expected a single character, got %r" % value)
    return value


def positive_int(value):
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer, got %r" % value)
    if iv <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer, got %r" % value)
    return iv


def build_parser():
    p = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge multiple CSV files into one schema-aligned, globally sorted CSV.",
    )
    p.add_argument("--output", required=True, metavar="PATH|-",
                   help="output CSV path, or '-' for stdout")
    p.add_argument("--key", required=True, metavar="col[,col...]",
                   help="comma separated composite sort key")
    p.add_argument("--desc", action="store_true",
                   help="sort descending (applies to all key columns)")
    p.add_argument("--schema", metavar="SCHEMA_JSON",
                   help="JSON file giving the exact output schema and column order")
    p.add_argument("--infer", choices=("strict", "loose"), default="strict",
                   help="type inference mode when --schema is not given (default: strict)")
    p.add_argument("--on-type-error", choices=("coerce-null", "fail", "keep-string"),
                   default="coerce-null", help="behaviour on cast failure (default: coerce-null)")
    p.add_argument("--memory-limit-mb", type=positive_int, default=128, metavar="INT",
                   help="approximate in-memory budget before spilling to disk (default: 128)")
    p.add_argument("--temp-dir", metavar="PATH", help="directory for temporary spill files")
    p.add_argument("--csv-quotechar", type=one_char, default='"', metavar="CHAR")
    p.add_argument("--csv-escapechar", type=one_char, default=None, metavar="CHAR")
    p.add_argument("--csv-null-literal", default="", metavar="STRING",
                   help="text emitted for null/missing values (default: empty string)")
    p.add_argument("inputs", nargs="*", metavar="INPUT.csv")
    return p


def run(args):
    inputs = list(args.inputs)
    if not inputs:
        raise UserError("no input files given")
    for path in inputs:
        if not os.path.isfile(path):
            raise UserError("input file not found: %s" % path)

    null_literal = args.csv_null_literal

    keys = [k for k in args.key.split(",")]
    keys = [k.strip() for k in keys]
    if not keys or any(k == "" for k in keys):
        raise UserError("--key must be a comma separated list of column names")

    if args.schema:
        columns = load_schema(args.schema)
    else:
        columns = infer_schema(inputs, args, null_literal)
    if not columns:
        raise UserError("no columns could be resolved from the inputs")

    names = [c[0] for c in columns]
    name_index = {}
    for i, n in enumerate(names):
        name_index.setdefault(n, i)
    missing = [k for k in keys if k not in name_index]
    if missing:
        raise UserError(
            "key column(s) not present in resolved schema: %s" % ", ".join(missing)
        )
    key_positions = [name_index[k] for k in keys]

    budget = max(1024 * 1024, int(args.memory_limit_mb * 1024 * 1024 * 0.35))

    tmpdir = None
    sorter = None
    out_fh = None
    close_out = False
    try:
        base_tmp = args.temp_dir
        if base_tmp:
            os.makedirs(base_tmp, exist_ok=True)
        tmpdir = tempfile.mkdtemp(prefix="merge_files_", dir=base_tmp)

        records = iter_records(inputs, columns, key_positions, args, null_literal)
        sorter = _Sorter(args.desc, budget, tmpdir)
        merged = sorter.sort(records)

        if args.output == "-":
            out_fh = os.fdopen(os.dup(sys.stdout.fileno()), "w",
                               encoding="utf-8", newline="")
            close_out = True
        else:
            out_fh = open(args.output, "w", encoding="utf-8", newline="")
            close_out = True

        writer = csv.writer(out_fh, **writer_kwargs(args))
        writer.writerow(names)
        for rec in merged:
            writer.writerow(rec[2])
        out_fh.flush()
    finally:
        if sorter is not None:
            sorter.close()
        if out_fh is not None and close_out:
            try:
                out_fh.close()
            except (OSError, ValueError):
                pass
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        csv.field_size_limit(2 ** 27)
    except (OverflowError, ValueError):
        pass
    try:
        return run(args)
    except UserError as exc:
        sys.stderr.write("merge_files.py: error: %s\n" % exc)
        return 1
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("merge_files.py: interrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())

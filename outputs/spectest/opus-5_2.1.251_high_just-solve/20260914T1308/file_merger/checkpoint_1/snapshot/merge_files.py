#!/usr/bin/env python3
"""Merge multiple CSV files into a single schema-aligned, globally sorted CSV.

The merge is performed with a bounded amount of memory: rows are cast to the
resolved schema, buffered until the memory budget is reached, spilled to sorted
temporary run files, and finally k-way merged onto the output stream.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import heapq
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

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


class UserError(Exception):
    """Fatal, user-facing error: reported on stderr with a non-zero exit."""


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
    raise UserError("unknown type %r" % typ)


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


class ColumnObserver:
    """Accumulates the intersection of candidate types over observed values."""

    def __init__(self):
        self.candidates = None  # None == nothing observed yet
        self.has_time = False
        self.observed = False

    def observe(self, text):
        self.observed = True
        candidates, has_time = value_candidates(text)
        self.has_time = self.has_time or has_time
        if self.candidates is None:
            self.candidates = set(candidates)
        else:
            self.candidates &= candidates

    def resolve(self):
        if not self.observed or not self.candidates:
            return "string"
        best = min(self.candidates, key=lambda t: TYPE_PRIORITY[t])
        # Keep pure date columns as dates: only promote to timestamp when a
        # value actually carried a time component.
        if best == "timestamp" and not self.has_time and "date" in self.candidates:
            return "date"
        return best


# --------------------------------------------------------------------------
# CSV plumbing
# --------------------------------------------------------------------------


@contextlib.contextmanager
def open_csv(path, dialect):
    try:
        handle = open(path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc.strerror or exc))
    try:
        reader = csv.reader(handle, **dialect)
        header = next(reader, None)
        yield header, reader
    finally:
        handle.close()


def header_index(header):
    """Map column name -> source index (first occurrence wins)."""
    index = {}
    for position, name in enumerate(header):
        if name not in index:
            index[name] = position
    return index


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
        raise UserError("invalid schema JSON: %s" % exc)

    columns = data.get("columns") if isinstance(data, dict) else data
    if not isinstance(columns, list) or not columns:
        raise UserError("schema must contain a non-empty 'columns' list")

    names, types = [], []
    for entry in columns:
        if isinstance(entry, str):
            name, typ = entry, "string"
        elif isinstance(entry, dict):
            name = entry.get("name")
            typ = entry.get("type", "string")
        else:
            raise UserError("invalid schema column entry: %r" % (entry,))
        if not isinstance(name, str) or not name:
            raise UserError("schema column is missing a name")
        if typ not in VALID_TYPES:
            raise UserError(
                "invalid type %r for column %r (valid: %s)" % (typ, name, ", ".join(VALID_TYPES))
            )
        if name in names:
            raise UserError("duplicate column %r in schema" % name)
        names.append(name)
        types.append(typ)
    return names, types


def infer_schema(inputs, dialect, mode, null_literal):
    """Infer column order (lexicographic) and types from the inputs."""
    all_names = set()
    # strict: per-file observations, conflicts across files fall back to string.
    # loose: one pooled observation per column, empty strings ignored.
    per_file = []
    pooled = {}

    for path in inputs:
        observers = {}
        with open_csv(path, dialect) as (header, reader):
            if header is None:
                per_file.append(observers)
                continue
            index = header_index(header)
            all_names.update(index)
            for name in index:
                observers.setdefault(name, ColumnObserver())
                pooled.setdefault(name, ColumnObserver())
            positions = list(index.items())
            loose = mode == "loose"
            for row in reader:
                if not row:
                    continue
                for name, position in positions:
                    text = row[position] if position < len(row) else ""
                    # An explicit null literal is a null in both modes; an empty
                    # string is a null only in loose mode.
                    if null_literal != "" and text == null_literal:
                        continue
                    if loose:
                        if text == "":
                            continue
                        observers[name].observe(text)
                        pooled[name].observe(text)
                    else:
                        observers[name].observe(text)
        per_file.append(observers)

    names = sorted(all_names)
    types = []
    for name in names:
        if mode == "loose":
            types.append(pooled[name].resolve())
            continue
        resolved = None
        conflict = False
        for observers in per_file:
            observer = observers.get(name)
            if observer is None or not observer.observed:
                continue
            candidate = observer.resolve()
            if resolved is None:
                resolved = candidate
            elif resolved != candidate:
                conflict = True
                break
        types.append("string" if (conflict or resolved is None) else resolved)
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
        path = tempfile.mktemp(prefix="merge_run_", suffix=".jsonl", dir=self.temp_dir)
        with open(path, "w", encoding="utf-8", newline="") as handle:
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
            try:
                os.unlink(path)
            except OSError:
                pass
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
        description="Merge multiple CSV files into one schema-aligned, sorted CSV.",
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
        "--on-type-error",
        choices=("coerce-null", "fail", "keep-string"),
        default="coerce-null",
    )
    parser.add_argument("--memory-limit-mb", type=int, default=64)
    parser.add_argument("--temp-dir", help="directory for intermediate run files")
    parser.add_argument("--csv-quotechar", type=single_char, default='"')
    parser.add_argument("--csv-escapechar", type=single_char, default=None)
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    return parser


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def run(args):
    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise UserError("--memory-limit-mb must be a positive integer")

    keys = []
    for chunk in args.key:
        for name in chunk.split(","):
            name = name.strip()
            if name and name not in keys:
                keys.append(name)
    if not keys:
        raise UserError("--key requires at least one column name")

    for path in args.inputs:
        if not os.path.isfile(path):
            raise UserError("input file not found: %s" % path)

    dialect = {
        "delimiter": ",",
        "quotechar": args.csv_quotechar,
        "escapechar": args.csv_escapechar,
        "doublequote": args.csv_escapechar is None,
    }
    null_literal = args.csv_null_literal

    if args.schema:
        names, types = load_schema(args.schema)
    else:
        names, types = infer_schema(args.inputs, dialect, args.infer, null_literal)

    if not names:
        raise UserError("no columns found in the inputs")

    missing = [k for k in keys if k not in names]
    if missing:
        raise UserError(
            "key column%s not present in resolved schema: %s"
            % ("" if len(missing) == 1 else "s", ", ".join(missing))
        )

    key_positions = [names.index(k) for k in keys]
    key_position_set = set(key_positions)
    on_type_error = args.on_type_error
    reverse = bool(args.desc)

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

    # Serialized records cost far less than the equivalent live Python objects,
    # so only part of the budget is handed to the sort buffer.
    budget = int(args.memory_limit_mb * 1024 * 1024 * 0.25)
    writer = RunWriter(temp_dir, budget, reverse)

    sequence = 0
    try:
        for path in args.inputs:
            with open_csv(path, dialect) as (header, reader):
                if header is None:
                    continue
                index = header_index(header)
                source = [index.get(name) for name in names]
                line_no = 1
                for row in reader:
                    line_no += 1
                    if not row:
                        continue
                    values = []
                    cell_keys = {}
                    for column_position, typ in enumerate(types):
                        position = source[column_position]
                        text = ""
                        if position is not None and position < len(row):
                            text = row[position]
                        if position is None or is_null_text(text, null_literal):
                            values.append(None)
                            if column_position in key_position_set:
                                cell_keys[column_position] = None
                            continue
                        ok, out, cell_key = cast_cell(typ, text)
                        if not ok:
                            if on_type_error == "fail":
                                raise UserError(
                                    "%s:%d: cannot cast %r to %s for column %r"
                                    % (path, line_no, text, typ, names[column_position])
                                )
                            if on_type_error == "keep-string":
                                out, cell_key = text, [1, 1, text]
                            else:  # coerce-null
                                out, cell_key = None, None
                        values.append(out)
                        if column_position in key_position_set:
                            cell_keys[column_position] = cell_key

                    # Key order follows --key; nulls sort before non-nulls in
                    # either direction (so they land last when reversed).
                    ordered_key = [
                        cell_keys.get(position) or [0] for position in key_positions
                    ]

                    sequence += 1
                    tiebreak = -sequence if reverse else sequence
                    record = [ordered_key, tiebreak, values]
                    approx = 96 + sum(len(v) + 48 for v in values if v is not None)
                    writer.add(record, approx)

        write_output(args.output, names, writer.sorted_records(), null_literal, dialect)
    finally:
        writer.cleanup()
        if owns_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


def write_output(destination, names, records, null_literal, dialect):
    out_dialect = {
        "delimiter": ",",
        "quotechar": dialect["quotechar"],
        "escapechar": dialect["escapechar"],
        "doublequote": dialect["doublequote"],
        "lineterminator": "\n",
        "quoting": csv.QUOTE_MINIMAL,
    }
    if destination == "-":
        handle = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="", closefd=False)
        close = True
    else:
        parent = os.path.dirname(os.path.abspath(destination))
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as exc:
                raise UserError("cannot create output directory: %s" % (exc.strerror or exc))
        try:
            handle = open(destination, "w", encoding="utf-8", newline="")
        except OSError as exc:
            raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))
        close = True
    try:
        out = csv.writer(handle, **out_dialect)
        out.writerow(names)
        for record in records:
            out.writerow([null_literal if v is None else v for v in record[2]])
        handle.flush()
    finally:
        if close:
            handle.close()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except UserError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return 2
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

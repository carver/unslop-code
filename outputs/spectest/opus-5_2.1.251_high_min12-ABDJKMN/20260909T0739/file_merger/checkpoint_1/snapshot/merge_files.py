#!/usr/bin/env python3
"""Merge several CSV files into a single schema-aligned, globally sorted CSV.

See AMBIGUITIES.md for the interpretation chosen wherever the spec left room.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import heapq
import io
import json
import os
import re
import sys
import tempfile
from contextlib import ExitStack
from datetime import date as date_cls, datetime, timedelta, timezone

PROG = "merge_files.py"

STRING, INT, FLOAT, BOOL, DATE, TIMESTAMP = (
    "string", "int", "float", "bool", "date", "timestamp",
)
VALID_TYPES = (STRING, INT, FLOAT, BOOL, DATE, TIMESTAMP)
# Spec: "Type priority: timestamp > date > bool > int > float > string"
TYPE_PRIORITY = (TIMESTAMP, DATE, BOOL, INT, FLOAT, STRING)

DEFAULT_MEMORY_LIMIT_MB = 64
MAX_MERGE_FANIN = 32

# Rank component of a sort key: nulls first, then well-typed values, then any
# raw text retained by --on-type-error keep-string.
RANK_NULL, RANK_VALUE, RANK_TEXT = 0, 1, 2

NULL, OK, ERR = "null", "ok", "err"


class ToolError(Exception):
    """An operational error: reported on stderr, exits non-zero."""


# --------------------------------------------------------------------------
# Scalar parsing
# --------------------------------------------------------------------------

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TIMESTAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ]"
    r"(\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?"
    r"(?:[ ]?(Z|z|[+-]\d{2}(?::?\d{2})?))?$"
)
BOOL_TRUE = frozenset(("true", "1"))
BOOL_FALSE = frozenset(("false", "0"))


def parse_int(text):
    if not INT_RE.match(text):
        return None
    return int(text)


def parse_float(text):
    if not FLOAT_RE.match(text):
        return None
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def parse_bool(text):
    lowered = text.lower()
    if lowered in BOOL_TRUE:
        return True
    if lowered in BOOL_FALSE:
        return False
    return None


def parse_date(text):
    match = DATE_RE.match(text)
    if not match:
        return None
    try:
        return date_cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_timestamp(text, allow_date_only=True):
    match = TIMESTAMP_RE.match(text)
    if not match:
        if allow_date_only:
            day = parse_date(text)
            if day is not None:
                return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        return None
    year, month, day, hour, minute, second, frac, zone = match.groups()
    micro = 0
    if frac:
        micro = int((frac[1:] + "000000")[:6])
    if zone in (None, "Z", "z"):
        tz = timezone.utc
    else:
        sign = -1 if zone[0] == "-" else 1
        body = zone[1:].replace(":", "")
        off_h = int(body[:2])
        off_m = int(body[2:4]) if len(body) > 2 else 0
        tz = timezone(sign * timedelta(hours=off_h, minutes=off_m))
    try:
        stamp = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=tz,
        )
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc)


PARSERS = {
    STRING: lambda text: text,
    INT: parse_int,
    FLOAT: parse_float,
    BOOL: parse_bool,
    DATE: parse_date,
    TIMESTAMP: parse_timestamp,
}


# --------------------------------------------------------------------------
# Scalar formatting (the output side of "cast every input cell")
# --------------------------------------------------------------------------

def format_timestamp(stamp):
    base = (
        f"{stamp.year:04d}-{stamp.month:02d}-{stamp.day:02d}"
        f"T{stamp.hour:02d}:{stamp.minute:02d}:{stamp.second:02d}"
    )
    if stamp.microsecond:
        base += "." + f"{stamp.microsecond:06d}".rstrip("0")
    return base + "Z"


def format_value(value, type_name):
    if type_name == STRING:
        return value
    if type_name == INT:
        return str(value)
    if type_name == FLOAT:
        return str(value)
    if type_name == BOOL:
        return "true" if value else "false"
    if type_name == DATE:
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    return format_timestamp(value)


def sort_value(value, type_name):
    """A JSON-serialisable, order-preserving projection of a typed value."""
    if type_name == BOOL:
        return 1 if value else 0
    if type_name == DATE:
        return value.toordinal()
    if type_name == TIMESTAMP:
        return value.timestamp()
    return value


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------

ALL_CANDIDATES = frozenset(VALID_TYPES)
STRING_ONLY = frozenset((STRING,))


def candidate_types(text, _cache={}):
    """Every type that can hold `text`."""
    cached = _cache.get(text)
    if cached is not None:
        return cached
    found = {STRING}
    if parse_int(text) is not None:
        found.add(INT)
    if parse_float(text) is not None:
        found.add(FLOAT)
    if parse_bool(text) is not None:
        found.add(BOOL)
    if parse_date(text) is not None:
        found.add(DATE)
    # A bare date is not a timestamp candidate: otherwise `date` could never be
    # inferred at all (timestamp outranks it).  See AMBIGUITIES T3.
    if parse_timestamp(text, allow_date_only=False) is not None:
        found.add(TIMESTAMP)
    result = frozenset(found)
    if len(_cache) < 100000:
        _cache[text] = result
    return result


def best_type(candidates):
    for type_name in TYPE_PRIORITY:
        if type_name in candidates:
            return type_name
    return STRING


# --------------------------------------------------------------------------
# CSV plumbing
# --------------------------------------------------------------------------

class Dialect:
    def __init__(self, quotechar, escapechar):
        self.quotechar = quotechar
        self.escapechar = escapechar

    def reader(self, stream):
        return csv.reader(
            stream,
            delimiter=",",
            quotechar=self.quotechar,
            escapechar=self.escapechar,
            doublequote=self.escapechar is None,
        )


def open_input(path):
    try:
        # utf-8-sig transparently drops a leading BOM if one is present.
        return open(path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ToolError(f"cannot read input {path!r}: {exc.strerror or exc}")


def read_header(path, dialect):
    """Return the header row of `path` ([] when the file is empty)."""
    with open_input(path) as stream:
        reader = dialect.reader(stream)
        try:
            header = next(reader, None)
        except csv.Error as exc:
            raise ToolError(f"{path}: malformed CSV: {exc}")
    return header or []


def column_index(header):
    """Map column name -> position, first occurrence winning."""
    index = {}
    for position, name in enumerate(header):
        if name not in index:
            index[name] = position
    return index


def iter_data_rows(path, dialect):
    """Yield (line_number, row) for every data row of `path`."""
    with open_input(path) as stream:
        reader = dialect.reader(stream)
        try:
            if next(reader, None) is None:
                return
            for row in reader:
                if not row:
                    continue  # a stray blank line is not a record
                yield reader.line_num, row
        except csv.Error as exc:
            raise ToolError(f"{path}: malformed CSV: {exc}")


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

class Column:
    __slots__ = ("name", "type")

    def __init__(self, name, type_name):
        self.name = name
        self.type = type_name


def load_schema(spec):
    """`--schema` names a JSON file; inline JSON is also accepted (T10)."""
    document = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as stream:
                document = json.load(stream)
        except OSError as exc:
            raise ToolError(f"cannot read schema {spec!r}: {exc.strerror or exc}")
        except ValueError as exc:
            raise ToolError(f"invalid schema JSON in {spec!r}: {exc}")
    else:
        stripped = spec.strip()
        if stripped.startswith("{"):
            try:
                document = json.loads(stripped)
            except ValueError as exc:
                raise ToolError(f"invalid schema JSON: {exc}")
        else:
            raise ToolError(f"schema file not found: {spec!r}")

    if not isinstance(document, dict) or not isinstance(document.get("columns"), list):
        raise ToolError("schema must be a JSON object with a 'columns' list")

    columns = []
    seen = set()
    for entry in document["columns"]:
        if not isinstance(entry, dict):
            raise ToolError("each schema column must be a JSON object")
        name = entry.get("name")
        if not isinstance(name, str) or name == "":
            raise ToolError("each schema column requires a non-empty 'name'")
        type_name = entry.get("type", STRING)
        if type_name not in VALID_TYPES:
            raise ToolError(
                f"invalid type {type_name!r} for column {name!r}; "
                f"valid types are: {', '.join(VALID_TYPES)}"
            )
        if name in seen:
            raise ToolError(f"duplicate column {name!r} in schema")
        seen.add(name)
        columns.append(Column(name, type_name))
    return columns


def infer_schema(paths, dialect, mode, is_null):
    """Union of all input headers, lexicographically ordered, with types."""
    names = set()
    headers = []
    for path in paths:
        header = read_header(path, dialect)
        headers.append(header)
        names.update(header)

    ordered = sorted(names)
    # strict: one type per (file, column); loose: one pooled candidate set.
    per_file_types = {name: set() for name in ordered}
    pooled = {name: None for name in ordered}

    for path, header in zip(paths, headers):
        if not header:
            continue
        index = column_index(header)
        local = {name: None for name in index}
        for _line, row in iter_data_rows(path, dialect):
            for name, position in index.items():
                text = row[position] if position < len(row) else ""
                if is_null(text):
                    if mode == "loose":
                        continue  # "empty strings ... don't affect inference"
                    found = STRING_ONLY
                else:
                    found = candidate_types(text)
                current = local[name]
                local[name] = found if current is None else (current & found)
        for name, candidates in local.items():
            if candidates is None:
                continue  # column present but with no observed values
            if mode == "loose":
                previous = pooled[name]
                pooled[name] = candidates if previous is None else previous & candidates
            else:
                per_file_types[name].add(best_type(candidates))

    columns = []
    for name in ordered:
        if mode == "loose":
            candidates = pooled[name]
            type_name = STRING if candidates is None else best_type(candidates)
        else:
            observed = per_file_types[name]
            type_name = observed.pop() if len(observed) == 1 else STRING
        columns.append(Column(name, type_name))
    return columns


# --------------------------------------------------------------------------
# External merge sort
# --------------------------------------------------------------------------

def make_record_key(descending):
    """Order records by key (optionally reversed) then by input appearance."""

    class RecordKey:
        __slots__ = ("key", "seq")

        def __init__(self, record):
            self.key = record[0]
            self.seq = record[1]

        def __lt__(self, other):
            if self.key == other.key:
                return self.seq < other.seq
            return self.key > other.key if descending else self.key < other.key

    return RecordKey


class RunStore:
    """Owns every spill file and guarantees their removal."""

    def __init__(self, temp_dir):
        self.temp_dir = temp_dir
        self.paths = []
        atexit.register(self.cleanup)

    def new_path(self):
        try:
            handle, path = tempfile.mkstemp(
                prefix="merge_files-", suffix=".jsonl", dir=self.temp_dir
            )
        except OSError as exc:
            raise ToolError(f"cannot create temporary file: {exc.strerror or exc}")
        os.close(handle)
        self.paths.append(path)
        return path

    def discard(self, path):
        try:
            os.unlink(path)
        except OSError:
            pass
        if path in self.paths:
            self.paths.remove(path)

    def cleanup(self):
        for path in list(self.paths):
            self.discard(path)


def write_run(records, path):
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_run(stream):
    for line in stream:
        if line:
            yield json.loads(line)


class Sorter:
    """Buffer records in memory up to a budget, spilling sorted runs to disk."""

    def __init__(self, budget_bytes, store, record_key):
        self.budget = budget_bytes
        self.store = store
        self.record_key = record_key
        self.buffer = []
        self.pending_bytes = 0

    def add(self, key, seq, row):
        self.buffer.append([key, seq, row])
        # Rough accounting: payload plus per-object interpreter overhead.
        self.pending_bytes += 120 + sum(len(cell) + 60 for cell in row)
        self.pending_bytes += 60 * len(key)
        if self.pending_bytes >= self.budget:
            self.spill()

    def spill(self):
        if not self.buffer:
            return
        self.buffer.sort(key=self.record_key)
        write_run(self.buffer, self.store.new_path())
        self.buffer = []
        self.pending_bytes = 0

    def _fold_runs(self, runs):
        while len(runs) > MAX_MERGE_FANIN:
            folded = []
            for start in range(0, len(runs), MAX_MERGE_FANIN):
                group = runs[start:start + MAX_MERGE_FANIN]
                if len(group) == 1:
                    folded.append(group[0])
                    continue
                target = self.store.new_path()
                with ExitStack() as stack:
                    out = stack.enter_context(
                        open(target, "w", encoding="utf-8", newline="\n")
                    )
                    sources = [
                        read_run(stack.enter_context(open(p, "r", encoding="utf-8")))
                        for p in group
                    ]
                    for record in heapq.merge(*sources, key=self.record_key):
                        out.write(json.dumps(record, separators=(",", ":")) + "\n")
                for path in group:
                    self.store.discard(path)
                folded.append(target)
            runs = folded
        return runs

    def sorted_rows(self, stack):
        """Yield output rows in final order. `stack` owns the run file handles."""
        if not self.store.paths:
            self.buffer.sort(key=self.record_key)
            for record in self.buffer:
                yield record[2]
            self.buffer = []
            return
        self.spill()
        runs = self._fold_runs(list(self.store.paths))
        sources = [
            read_run(stack.enter_context(open(path, "r", encoding="utf-8")))
            for path in runs
        ]
        for record in heapq.merge(*sources, key=self.record_key):
            yield record[2]


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Merge multiple CSV files into one schema-aligned, sorted CSV.",
    )
    parser.add_argument("--output", required=True, metavar="PATH|-",
                        help="output CSV path, or '-' for stdout")
    parser.add_argument("--key", required=True, action="append", metavar="COL[,COL...]",
                        help="sort key column(s); may be repeated")
    parser.add_argument("--desc", action="store_true",
                        help="sort every key in descending order")
    parser.add_argument("--schema", metavar="SCHEMA_JSON",
                        help="JSON file giving the exact output schema and order")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict",
                        help="type inference mode when --schema is absent")
    parser.add_argument("--on-type-error", dest="on_type_error",
                        choices=("coerce-null", "fail", "keep-string"),
                        default="coerce-null", help="behaviour on a failed cast")
    parser.add_argument("--memory-limit-mb", dest="memory_limit_mb", type=int,
                        default=DEFAULT_MEMORY_LIMIT_MB, metavar="INT",
                        help="approximate in-memory budget before spilling to disk")
    parser.add_argument("--temp-dir", dest="temp_dir", metavar="PATH",
                        help="directory for intermediate spill files")
    parser.add_argument("--csv-quotechar", dest="csv_quotechar", default='"',
                        metavar="CHAR", help="input quote character (default: \")")
    parser.add_argument("--csv-escapechar", dest="csv_escapechar", default=None,
                        metavar="CHAR",
                        help="input escape character (default: doubled quotes)")
    parser.add_argument("--csv-null-literal", dest="csv_null_literal", default="",
                        metavar="STRING", help="text used for null cells")
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    return parser


def parse_key_columns(values):
    columns = []
    for value in values:
        for part in value.split(","):
            name = part.strip()
            if not name:
                raise ToolError("--key must name at least one non-empty column")
            if name not in columns:
                columns.append(name)
    if not columns:
        raise ToolError("--key must name at least one column")
    return columns


def make_null_test(literal):
    if literal == "":
        return lambda text: text == ""
    return lambda text: text == "" or text == literal


def open_output(path):
    if path == "-":
        return io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        ), False
    try:
        return open(path, "w", encoding="utf-8", newline=""), True
    except OSError as exc:
        raise ToolError(f"cannot write output {path!r}: {exc.strerror or exc}")


def run(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if len(args.csv_quotechar) != 1:
        raise ToolError("--csv-quotechar must be exactly one character")
    if args.csv_escapechar is not None and len(args.csv_escapechar) != 1:
        raise ToolError("--csv-escapechar must be exactly one character")
    if args.memory_limit_mb <= 0:
        raise ToolError("--memory-limit-mb must be a positive integer")
    if args.temp_dir is not None and not os.path.isdir(args.temp_dir):
        raise ToolError(f"--temp-dir is not a directory: {args.temp_dir!r}")

    for path in args.inputs:
        if not os.path.exists(path):
            raise ToolError(f"input file not found: {path}")
        if os.path.isdir(path):
            raise ToolError(f"input is a directory: {path}")

    key_names = parse_key_columns(args.key)
    null_literal = args.csv_null_literal
    is_null = make_null_test(null_literal)
    dialect = Dialect(args.csv_quotechar, args.csv_escapechar)

    # --- resolve the schema -------------------------------------------------
    if args.schema is not None:
        columns = load_schema(args.schema)
    else:
        columns = infer_schema(args.inputs, dialect, args.infer, is_null)

    positions = {column.name: i for i, column in enumerate(columns)}
    for name in key_names:
        if name not in positions:
            raise ToolError(
                f"key column {name!r} is not present in the resolved schema "
                f"({', '.join(c.name for c in columns) or 'no columns'})"
            )
    key_positions = [positions[name] for name in key_names]
    types = [column.type for column in columns]
    header = [column.name for column in columns]

    budget = max(int(args.memory_limit_mb * 1024 * 1024 * 0.6), 256 * 1024)
    store = RunStore(args.temp_dir)
    record_key = make_record_key(args.desc)
    sorter = Sorter(budget, store, record_key)

    out_stream, close_out = None, False
    try:
        seq = 0
        for path in args.inputs:
            header_row = read_header(path, dialect)
            if not header_row:
                continue
            index = column_index(header_row)
            # Per output column: the source position, or None when absent.
            sources = [index.get(column.name) for column in columns]
            for line_no, row in iter_data_rows(path, dialect):
                out_row = []
                key = []
                for slot, source in enumerate(sources):
                    type_name = types[slot]
                    if source is None or source >= len(row):
                        raw = None
                    else:
                        raw = row[source]
                    status, value = cast_cell(raw, type_name, is_null)
                    if status == NULL:
                        text, cell_key = null_literal, [RANK_NULL, 0]
                    elif status == OK:
                        text = format_value(value, type_name)
                        cell_key = [RANK_VALUE, sort_value(value, type_name)]
                    elif args.on_type_error == "coerce-null":
                        text, cell_key = null_literal, [RANK_NULL, 0]
                    elif args.on_type_error == "keep-string":
                        text, cell_key = raw, [RANK_TEXT, raw]
                    else:
                        raise ToolError(
                            f"{path}:{line_no}: cannot cast {raw!r} in column "
                            f"{header[slot]!r} to {type_name}"
                        )
                    out_row.append(text)
                    key.append(cell_key)
                sorter.add([key[p] for p in key_positions], seq, out_row)
                seq += 1

        with ExitStack() as stack:
            rows = sorter.sorted_rows(stack)
            out_stream, close_out = open_output(args.output)
            writer = csv.writer(
                out_stream, delimiter=",", quotechar='"', doublequote=True,
                lineterminator="\n", quoting=csv.QUOTE_MINIMAL,
            )
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
            out_stream.flush()
    finally:
        store.cleanup()
        if out_stream is not None:
            if close_out:
                out_stream.close()
            else:
                try:
                    out_stream.flush()
                    out_stream.detach()
                except (ValueError, OSError):
                    pass
    return 0


def cast_cell(raw, type_name, is_null):
    """Cast one raw cell; `raw is None` means the column is absent from the row."""
    if raw is None or is_null(raw):
        return NULL, None
    value = PARSERS[type_name](raw)
    if value is None:
        return ERR, None
    return OK, value


def main(argv=None):
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except ToolError as exc:
        sys.stderr.write(f"{PROG}: error: {exc}\n")
        return 1
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

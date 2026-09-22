#!/usr/bin/env python3
"""Merge several CSV files into one schema-aligned, globally sorted CSV.

See AMBIGUITIES.md for the readings chosen where the spec allows more than one.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import io
import json
import os
import pickle
import re
import shutil
import sys
import tempfile
from datetime import date as _date
from datetime import datetime, timedelta, timezone

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
STRING_ONLY = 1 << TYPE_PRIORITY.index(STRING)

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


class ToolError(Exception):
    """A user-facing error: reported on stderr, exits non-zero."""


class CastError(Exception):
    pass


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


def top_type(bits):
    for name in TYPE_PRIORITY:
        if bits & TYPE_BIT[name]:
            return name
    return STRING


def infer_schema(inputs, columns, dialect, null_literal, mode):
    """Return {column: type} inferred from every value in every input."""
    # per file: column -> bitmask of types every observed value fits
    per_file = []
    for path in inputs:
        masks = {}
        with open_input(path) as handle:
            reader = make_reader(handle, dialect)
            header = read_header(reader)
            index = column_index(header, columns)
            for row in reader:
                if not row:
                    continue
                for name in columns:
                    pos = index[name]
                    if pos is None or pos >= len(row):
                        continue
                    cell = row[pos]
                    if is_null_text(cell, null_literal):
                        continue
                    bits = masks.get(name, ALL_BITS)
                    # `string` fits everything, so it is the floor: once a
                    # column is down to it, further values cannot narrow it.
                    if bits != STRING_ONLY:
                        bits &= candidate_bits(cell)
                    masks[name] = bits
        per_file.append(masks)

    schema = {}
    for name in columns:
        observed = [masks[name] for masks in per_file if name in masks]
        if not observed:
            schema[name] = STRING
            continue
        if mode == "loose":
            bits = ALL_BITS
            for value in observed:
                bits &= value
            schema[name] = top_type(bits)
        else:
            types = {top_type(bits) for bits in observed}
            schema[name] = types.pop() if len(types) == 1 else STRING
    return schema


# --------------------------------------------------------------------------
# CSV plumbing
# --------------------------------------------------------------------------


class Dialect:
    def __init__(self, quotechar, escapechar):
        self.quotechar = quotechar
        self.escapechar = escapechar


def open_input(path):
    try:
        return open(path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ToolError("cannot read input %s: %s" % (path, exc.strerror or exc))


def make_reader(handle, dialect):
    return csv.reader(
        handle,
        delimiter=",",
        quotechar=dialect.quotechar,
        doublequote=True,
        escapechar=dialect.escapechar,
        strict=False,
    )


def read_header(reader):
    for row in reader:
        return [cell for cell in row]
    return []


def column_index(header, columns):
    lookup = {}
    for pos, name in enumerate(header):
        lookup.setdefault(name, pos)
    return {name: lookup.get(name) for name in columns}


def is_null_text(cell, null_literal):
    if cell == "":
        return True
    return bool(null_literal) and cell == null_literal


def read_headers(inputs, dialect):
    headers = []
    for path in inputs:
        with open_input(path) as handle:
            headers.append(read_header(make_reader(handle, dialect)))
    return headers


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
# Main pipeline
# --------------------------------------------------------------------------


def load_schema(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise ToolError("cannot read schema %s: %s" % (path, exc.strerror or exc))
    except ValueError as exc:
        raise ToolError("invalid schema JSON in %s: %s" % (path, exc))
    if not isinstance(document, dict) or not isinstance(
        document.get("columns"), list
    ):
        raise ToolError("schema %s must be an object with a 'columns' list" % path)
    columns = []
    types = {}
    for entry in document["columns"]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ToolError("schema column entries need a 'name': %r" % (entry,))
        name = entry["name"]
        type_name = entry.get("type", STRING)
        if type_name not in VALID_TYPES:
            raise ToolError(
                "invalid column type %r for column %r (valid: %s)"
                % (type_name, name, ", ".join(VALID_TYPES))
            )
        columns.append(name)
        types[name] = type_name
    return columns, types


def resolve_schema(args, dialect):
    if args.schema:
        return load_schema(args.schema)
    headers = read_headers(args.inputs, dialect)
    names = set()
    for header in headers:
        names.update(header)
    columns = sorted(names)
    types = infer_schema(
        args.inputs, columns, dialect, args.csv_null_literal, args.infer
    )
    return columns, types


def build_records(args, columns, types, dialect, sorter):
    """Cast every input cell, feeding sortable records to the sorter."""
    null_literal = args.csv_null_literal
    key_positions = [columns.index(name) for name in args.key]
    seq = 0
    for path in args.inputs:
        with open_input(path) as handle:
            reader = make_reader(handle, dialect)
            header = read_header(reader)
            index = column_index(header, columns)
            positions = [index[name] for name in columns]
            column_types = [types[name] for name in columns]
            line = 1
            for row in reader:
                line += 1
                if not row:
                    continue
                out_row = []
                comps = []
                for offset, name in enumerate(columns):
                    pos = positions[offset]
                    type_name = column_types[offset]
                    cell = row[pos] if pos is not None and pos < len(row) else ""
                    if is_null_text(cell, null_literal):
                        out_row.append(null_literal)
                        comps.append(NULL_COMP)
                        continue
                    try:
                        value = CASTERS[type_name](cell)
                    except CastError:
                        if args.on_type_error == "fail":
                            raise ToolError(
                                "%s:%d: cannot cast %r to %s for column %r"
                                % (path, line, cell, type_name, name)
                            )
                        if args.on_type_error == "keep-string":
                            out_row.append(cell)
                            comps.append((RANK_STRING, cell))
                        else:
                            out_row.append(null_literal)
                            comps.append(NULL_COMP)
                        continue
                    out_row.append(format_value(type_name, value))
                    comps.append(comparable(type_name, value))
                key = tuple(comps[pos] for pos in key_positions)
                sorter.add((key, seq, out_row))
                seq += 1


def write_output(destination, columns, records):
    if destination == "-":
        stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        )
        close = False
    else:
        try:
            stream = open(destination, "w", encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(
                "cannot write output %s: %s" % (destination, exc.strerror or exc)
            )
        close = True
    try:
        writer = csv.writer(
            stream,
            delimiter=",",
            quotechar='"',
            doublequote=True,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerow(columns)
        for _key, _seq, row in records:
            writer.writerow(row)
        stream.flush()
    finally:
        if close:
            stream.close()
        else:
            try:
                stream.detach()
            except Exception:
                pass


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
        description="Merge CSV files into one schema-aligned, sorted CSV.",
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
    parser.add_argument("--schema", help="JSON file with the exact output schema")
    parser.add_argument(
        "--infer", choices=("strict", "loose"), default="strict",
        help="type inference mode when no schema is given",
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
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
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
    dialect = Dialect(args.csv_quotechar, args.csv_escapechar)
    for path in args.inputs:
        if not os.path.exists(path):
            raise ToolError("input file not found: %s" % path)
    columns, types = resolve_schema(args, dialect)
    missing = [name for name in args.key if name not in columns]
    if missing:
        raise ToolError(
            "key column(s) not present in resolved schema: %s" % ", ".join(missing)
        )

    scratch = tempfile.mkdtemp(prefix="merge_files-", dir=args.temp_dir)
    sorter = ExternalSorter(scratch, args.memory_limit_mb, args.desc)
    try:
        build_records(args, columns, types, dialect, sorter)
        write_output(args.output, columns, sorter.sorted_records())
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
        return 1
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

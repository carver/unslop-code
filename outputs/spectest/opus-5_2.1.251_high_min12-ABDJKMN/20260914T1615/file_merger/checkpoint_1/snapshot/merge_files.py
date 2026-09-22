#!/usr/bin/env python3
"""Merge multiple CSV files into one schema-aligned, globally sorted CSV.

See AMBIGUITIES.md for the interpretation chosen wherever the spec left room.
"""

import argparse
import atexit
import csv
import heapq
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from functools import cmp_to_key

PROG = "merge_files.py"

# Type priority, highest first: timestamp > date > bool > int > float > string
PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")
VALID_TYPES = frozenset(PRIORITY)
BIT = {t: 1 << i for i, t in enumerate(PRIORITY)}
ALL_BITS = (1 << len(PRIORITY)) - 1

# Merging more runs than this at once risks exhausting file descriptors, so
# deep run sets are merged in several passes.
MAX_FANIN = 32

# Rough per-object overheads used to keep the in-memory buffer inside the
# --memory-limit-mb budget (CPython list slots + str/int object headers).
ROW_OVERHEAD = 200
CELL_OVERHEAD = 60
KEY_OVERHEAD = 120

# Key-token ranks: cast values sort before values kept as raw text (keep-string).
RANK_VALUE = 0
RANK_RAW = 1


class Fatal(Exception):
    """An error that should be reported on stderr with a non-zero exit."""


# --------------------------------------------------------------------------
# Parsing of cell text
# --------------------------------------------------------------------------

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TS_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[T ](?P<time>\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?"
    r"(?P<zone>[Zz]|[+-]\d{2}:?\d{2}(?::\d{2})?)?$"
)
BOOL_TRUE = frozenset(("true", "1"))
BOOL_FALSE = frozenset(("false", "0"))


def parse_int(text):
    if INT_RE.match(text):
        return int(text)
    return None


def parse_float(text):
    if FLOAT_RE.match(text):
        try:
            return float(text)
        except ValueError:  # pragma: no cover - regex already guarantees this
            return None
    return None


def parse_bool(text):
    low = text.lower()
    if low in BOOL_TRUE:
        return True
    if low in BOOL_FALSE:
        return False
    return None


def parse_date(text):
    if not DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_timestamp(text, require_time=False):
    m = TS_RE.match(text)
    if not m:
        return None
    if require_time and m.group("time") is None:
        return None
    parts = [m.group("date")]
    time_part = m.group("time") or "00:00:00"
    if "." in time_part:
        head, frac = time_part.split(".", 1)
        frac = (frac + "000000")[:6]
        time_part = head + "." + frac
    parts.append("T" + time_part)
    zone = m.group("zone")
    if zone in (None, "Z", "z"):
        zone = "+00:00"
    elif ":" not in zone:
        zone = zone[:3] + ":" + zone[3:]
    parts.append(zone)
    try:
        dt = datetime.fromisoformat("".join(parts))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


PARSERS = {
    "string": lambda text: text,
    "int": parse_int,
    "float": parse_float,
    "bool": parse_bool,
    "date": parse_date,
    "timestamp": parse_timestamp,
}


def candidate_bits(text):
    """Bitmask of the types `text` could be, used for schema inference."""
    bits = BIT["string"]
    if parse_int(text) is not None:
        bits |= BIT["int"]
    if parse_float(text) is not None:
        bits |= BIT["float"]
    if parse_bool(text) is not None:
        bits |= BIT["bool"]
    if parse_date(text) is not None:
        bits |= BIT["date"]
    # A bare date is a `date`, not a `timestamp`: inference needs a time part.
    if parse_timestamp(text, require_time=True) is not None:
        bits |= BIT["timestamp"]
    return bits


def best_type(bits):
    for t in PRIORITY:
        if bits & BIT[t]:
            return t
    return "string"


# --------------------------------------------------------------------------
# Rendering of cast values
# --------------------------------------------------------------------------

def render_timestamp(dt):
    out = (
        f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        f"T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    )
    if dt.microsecond:
        out += ("." + f"{dt.microsecond:06d}".rstrip("0"))
    return out + "Z"


def render(typ, value):
    if typ == "string":
        return value
    if typ == "int":
        return str(value)
    if typ == "float":
        return repr(value)
    if typ == "bool":
        return "true" if value else "false"
    if typ == "date":
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    return render_timestamp(value)


def sort_payload(typ, value):
    """A JSON-serializable, order-preserving stand-in for a cast value."""
    if typ == "string":
        return value
    if typ in ("int", "float"):
        return value
    if typ == "bool":
        return 1 if value else 0
    if typ == "date":
        return value.toordinal()
    return value.timestamp()


# --------------------------------------------------------------------------
# Argument handling
# --------------------------------------------------------------------------

def one_char(name):
    def check(value):
        if len(value) != 1:
            raise argparse.ArgumentTypeError(f"{name} must be exactly one character")
        return value
    return check


def build_parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Merge multiple CSVs into one schema-aligned, sorted CSV.",
    )
    p.add_argument("--output", required=True, metavar="PATH|-",
                   help="output CSV path, or - for stdout")
    p.add_argument("--key", required=True, action="append", metavar="COL[,COL...]",
                   help="sort key column(s); may be repeated or comma-separated")
    p.add_argument("--desc", action="store_true",
                   help="sort all key columns in descending order")
    p.add_argument("--schema", metavar="SCHEMA_JSON",
                   help="path to a JSON schema document (or literal JSON)")
    p.add_argument("--infer", choices=("strict", "loose"), default="strict",
                   help="type inference mode when no schema is given")
    p.add_argument("--on-type-error", choices=("coerce-null", "fail", "keep-string"),
                   default="coerce-null", dest="on_type_error",
                   help="what to do when a cell fails to cast")
    p.add_argument("--memory-limit-mb", type=int, default=64, dest="memory_limit_mb",
                   help="approximate in-memory budget before spilling to disk")
    p.add_argument("--temp-dir", dest="temp_dir", metavar="PATH",
                   help="directory to hold intermediate spill files")
    p.add_argument("--csv-quotechar", dest="quotechar", default='"',
                   type=one_char("--csv-quotechar"))
    p.add_argument("--csv-escapechar", dest="escapechar", default=None,
                   type=one_char("--csv-escapechar"))
    p.add_argument("--csv-null-literal", dest="null_literal", default="")
    p.add_argument("inputs", nargs="+", metavar="INPUT.csv")
    return p


def parse_args(argv):
    args = build_parser().parse_args(argv)
    keys = []
    for spec in args.key:
        for name in spec.split(","):
            keys.append(name.strip())
    if not keys or any(k == "" for k in keys):
        raise Fatal("--key must name at least one column")
    args.keys = keys
    if args.memory_limit_mb <= 0:
        raise Fatal("--memory-limit-mb must be a positive integer")
    return args


# --------------------------------------------------------------------------
# CSV input
# --------------------------------------------------------------------------

class Dialect:
    def __init__(self, quotechar, escapechar):
        self.quotechar = quotechar
        self.escapechar = escapechar

    def reader(self, fh):
        kwargs = dict(delimiter=",", quotechar=self.quotechar, doublequote=True)
        if self.escapechar is not None:
            kwargs["escapechar"] = self.escapechar
        return csv.reader(fh, **kwargs)


def open_input(path):
    try:
        return open(path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise Fatal(f"cannot read input {path}: {exc}")


def read_header(path, dialect):
    with open_input(path) as fh:
        for row in dialect.reader(fh):
            return row
    return []


def iter_rows(path, dialect):
    """Yield (line_number, row) for every data row of `path`."""
    with open_input(path) as fh:
        reader = dialect.reader(fh)
        try:
            first = True
            for row in reader:
                if first:
                    first = False
                    continue
                yield reader.line_num, row
        except csv.Error as exc:
            raise Fatal(f"malformed CSV in {path}: {exc}")


def column_index_map(header, names):
    """Map each schema column name to its index in `header` (-1 when absent).

    The first occurrence of a duplicated header name wins.
    """
    positions = {}
    for i, name in enumerate(header):
        positions.setdefault(name, i)
    return [positions.get(name, -1) for name in names]


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

def load_schema_document(spec):
    text = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise Fatal(f"cannot read schema {spec}: {exc}")
    else:
        text = spec
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise Fatal(f"invalid schema JSON: {exc}")
    if not isinstance(doc, dict) or not isinstance(doc.get("columns"), list):
        raise Fatal('schema must be a JSON object with a "columns" array')
    names, types = [], []
    for entry in doc["columns"]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise Fatal('each schema column needs a "name"')
        name = entry["name"]
        typ = entry.get("type", "string")
        if not isinstance(name, str):
            raise Fatal("schema column names must be strings")
        if typ not in VALID_TYPES:
            raise Fatal(
                f"unknown type {typ!r} for column {name!r}; "
                f"valid types are {', '.join(sorted(VALID_TYPES))}"
            )
        if name in names:
            raise Fatal(f"duplicate column {name!r} in schema")
        names.append(name)
        types.append(typ)
    return names, types


def infer_schema(inputs, dialect, mode):
    """Infer (names, types) from the union of all input headers and values."""
    names = set()
    headers = []
    for path in inputs:
        header = read_header(path, dialect)
        headers.append(header)
        names.update(header)
    names = sorted(names)
    index = {name: i for i, name in enumerate(names)}

    # Per-file candidate bitmask and "saw a non-null value" flag per column.
    per_file = []
    for path, header in zip(inputs, headers):
        cols = column_index_map(header, names)
        bits = [ALL_BITS] * len(names)
        seen = [False] * len(names)
        for _lineno, row in iter_rows(path, dialect):
            width = len(row)
            for i, src in enumerate(cols):
                if src < 0 or src >= width:
                    continue
                text = row[src]
                if text == "":
                    continue  # empty strings are nulls; they don't affect inference
                seen[i] = True
                if bits[i]:
                    bits[i] &= candidate_bits(text)
        per_file.append((bits, seen))

    types = []
    for i, name in enumerate(names):
        if mode == "loose":
            merged = ALL_BITS
            evidence = False
            for bits, seen in per_file:
                if seen[i]:
                    evidence = True
                    merged &= bits[i]
            types.append(best_type(merged) if evidence else "string")
        else:
            found = set()
            for bits, seen in per_file:
                if seen[i]:
                    found.add(best_type(bits[i]))
            if len(found) == 1:
                types.append(found.pop())
            else:
                types.append("string")
    return names, types


# --------------------------------------------------------------------------
# Casting
# --------------------------------------------------------------------------

class Caster:
    def __init__(self, names, types, on_type_error):
        self.names = names
        self.types = types
        self.on_type_error = on_type_error

    def cast(self, text, col_index, where):
        """Return (output_text_or_None, key_token_or_None)."""
        typ = self.types[col_index]
        if text is None or text == "":
            return None, None
        value = PARSERS[typ](text)
        if value is None:
            if self.on_type_error == "fail":
                raise Fatal(
                    f"{where}: cannot cast {text!r} to {typ} "
                    f"(column {self.names[col_index]!r})"
                )
            if self.on_type_error == "keep-string":
                return text, [RANK_RAW, text]
            return None, None
        return render(typ, value), [RANK_VALUE, sort_payload(typ, value)]


# --------------------------------------------------------------------------
# Sorting
# --------------------------------------------------------------------------

def make_comparator(n_keys, desc):
    def compare(a, b):
        ka, kb = a[0], b[0]
        for i in range(n_keys):
            ta = ka[i]
            tb = kb[i]
            if ta is None:
                if tb is None:
                    continue
                # Nulls always compare less than non-nulls: first ascending,
                # last descending.
                return 1 if desc else -1
            if tb is None:
                return -1 if desc else 1
            if ta == tb:
                continue
            result = -1 if ta < tb else 1
            return -result if desc else result
        # Stable with respect to input appearance, in both directions.
        sa, sb = a[1], b[1]
        return -1 if sa < sb else (1 if sa > sb else 0)
    return compare


class SpillStore:
    """Holds sorted runs on disk so arbitrarily large inputs can be merged."""

    def __init__(self, temp_dir):
        self.requested = temp_dir
        self.dir = None
        self.paths = []
        self.counter = 0
        if temp_dir is not None and not os.path.isdir(temp_dir):
            raise Fatal(f"--temp-dir {temp_dir} is not an existing directory")
        atexit.register(self.cleanup)

    def _ensure_dir(self):
        if self.dir is None:
            try:
                self.dir = tempfile.mkdtemp(prefix="merge_files-", dir=self.requested)
            except OSError as exc:
                raise Fatal(f"cannot create temporary directory: {exc}")
        return self.dir

    def _new_path(self):
        self.counter += 1
        return os.path.join(self._ensure_dir(), f"run-{self.counter:08d}.jsonl")

    def _write_run(self, records):
        path = self._new_path()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, ensure_ascii=False))
                    fh.write("\n")
        except OSError as exc:
            raise Fatal(f"cannot write temporary file: {exc}")
        return path

    def spill(self, records):
        self.paths.append(self._write_run(records))

    def reduce_runs(self, sort_key):
        """Merge runs in passes until few enough remain to merge in one go."""
        while len(self.paths) > MAX_FANIN:
            merged = []
            for i in range(0, len(self.paths), MAX_FANIN):
                group = self.paths[i:i + MAX_FANIN]
                if len(group) == 1:
                    merged.append(group[0])
                    continue
                handles = [open(g, "r", encoding="utf-8") for g in group]
                try:
                    stream = heapq.merge(*[_json_lines(h) for h in handles],
                                         key=sort_key)
                    merged.append(self._write_run(stream))
                finally:
                    for handle in handles:
                        handle.close()
                for g in group:
                    try:
                        os.remove(g)
                    except OSError:
                        pass
            self.paths = merged
        return self.paths

    def cleanup(self):
        if self.dir is not None and os.path.isdir(self.dir):
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = None
        self.paths = []


def read_run(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line:
                yield json.loads(line)


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def ingest(args, names, types, dialect, caster, store):
    """Read every input, cast cells, and produce sorted runs.

    Returns (in_memory_records, run_paths). When run_paths is empty the whole
    dataset is in memory.
    """
    key_positions = [names.index(k) for k in args.keys]
    budget = max(int(args.memory_limit_mb * 1024 * 1024 * 0.6), 256 * 1024)
    compare = make_comparator(len(key_positions), args.desc)
    sort_key = cmp_to_key(compare)

    buffer = []
    used = 0
    seq = 0
    n_cols = len(names)

    # Where each key column lands inside the per-row token list.
    key_slots = {}
    for slot, col in enumerate(key_positions):
        key_slots.setdefault(col, []).append(slot)

    for path in args.inputs:
        header = read_header(path, dialect)
        cols = column_index_map(header, names)
        for lineno, row in iter_rows(path, dialect):
            width = len(row)
            cells = [None] * n_cols
            tokens = [None] * len(key_positions)
            approx = ROW_OVERHEAD + 8 * n_cols + KEY_OVERHEAD * len(key_positions)
            where = f"{path}:{lineno}"
            for i in range(n_cols):
                src = cols[i]
                text = row[src] if 0 <= src < width else ""
                if text == "" and i not in key_slots:
                    continue
                out, token = caster.cast(text, i, where)
                cells[i] = out
                if out is not None:
                    approx += len(out) + CELL_OVERHEAD
                for slot in key_slots.get(i, ()):
                    tokens[slot] = token
            buffer.append([tokens, seq, cells])
            seq += 1
            used += approx
            if used >= budget:
                buffer.sort(key=sort_key)
                store.spill(buffer)
                buffer = []
                used = 0

    if store.paths and buffer:
        buffer.sort(key=sort_key)
        store.spill(buffer)
        buffer = []
    return buffer, sort_key


def open_output(destination):
    if destination == "-":
        stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="")
        return stream, False
    try:
        stream = open(destination, "w", encoding="utf-8", newline="")
    except OSError as exc:
        raise Fatal(f"cannot write output {destination}: {exc}")
    return stream, True


def write_output(args, names, records, store, sort_key):
    if store.paths:
        store.reduce_runs(sort_key)
    else:
        records.sort(key=sort_key)
    stream, closable = open_output(args.output)
    handles = []
    try:
        writer = csv.writer(
            stream,
            delimiter=",",
            quotechar=args.quotechar,
            doublequote=True,
            escapechar=None,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerow(names)
        if store.paths:
            runs = []
            for path in store.paths:
                handle = open(path, "r", encoding="utf-8")
                handles.append(handle)
                runs.append(_json_lines(handle))
            rows = heapq.merge(*runs, key=sort_key)
        else:
            rows = records
        null_literal = args.null_literal
        for rec in rows:
            cells = rec[2]
            writer.writerow([null_literal if c is None else c for c in cells])
        stream.flush()
    except OSError as exc:
        raise Fatal(f"cannot write output: {exc}")
    finally:
        for handle in handles:
            handle.close()
        if closable:
            stream.close()
        else:
            stream.detach()


def _json_lines(handle):
    for line in handle:
        if line:
            yield json.loads(line)


def run(argv=None):
    args = parse_args(argv)
    dialect = Dialect(args.quotechar, args.escapechar)

    for path in args.inputs:
        if not os.path.exists(path):
            raise Fatal(f"input file not found: {path}")

    if args.schema is not None:
        names, types = load_schema_document(args.schema)
    else:
        names, types = infer_schema(args.inputs, dialect, args.infer)

    missing = [k for k in args.keys if k not in names]
    if missing:
        raise Fatal(
            "key column(s) not present in resolved schema: " + ", ".join(missing)
        )

    caster = Caster(names, types, args.on_type_error)

    store = SpillStore(args.temp_dir)
    try:
        records, sort_key = ingest(args, names, types, dialect, caster, store)
        write_output(args, names, records, store, sort_key)
    finally:
        store.cleanup()
    return 0


def main(argv=None):
    try:
        return run(argv)
    except Fatal as exc:
        sys.stderr.write(f"{PROG}: error: {exc}\n")
        return 1
    except BrokenPipeError:  # pragma: no cover - downstream closed stdout
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    sys.exit(main())

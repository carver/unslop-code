#!/usr/bin/env python3
"""Merge multiple CSV files into a single schema-aligned, globally sorted CSV.

The tool aligns the schemas of all inputs (either from an explicit schema file or
by inference over the union of the input headers), casts every cell into the
resolved column type and emits one CSV sorted by a composite key.

Sorting is performed with an external merge sort so that inputs far larger than
the configured memory limit can be processed.
"""

from __future__ import annotations

import argparse
import atexit
import csv
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
from datetime import date as date_cls, datetime, timedelta, timezone

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


class MergeError(Exception):
    """Fatal, user facing error."""


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


def cast_cell(raw: str, type_name: str):
    """Cast ``raw`` to ``type_name``; return (sort_value, output_text)."""
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


def _resolve_candidates(candidates: set) -> str:
    for type_name in TYPE_PRIORITY:
        if type_name == "string":
            return "string"
        if type_name in candidates:
            return type_name
    return "string"


class ColumnObserver:
    """Tracks which types remain possible for the values seen in one column."""

    __slots__ = ("candidates", "seen")

    def __init__(self):
        self.candidates = set(_CANDIDATE_TYPES)
        self.seen = False

    def observe(self, value: str) -> None:
        self.seen = True
        if not self.candidates:
            return
        dead = [t for t in self.candidates if not _matches(value, t)]
        if dead:
            self.candidates.difference_update(dead)

    def resolve(self) -> str:
        return _resolve_candidates(self.candidates)


# --------------------------------------------------------------------------
# CSV plumbing
# --------------------------------------------------------------------------

def read_dialect_kwargs(args) -> dict:
    return {
        "delimiter": ",",
        "quotechar": args.csv_quotechar,
        "doublequote": True,
        "escapechar": args.csv_escapechar,
        "lineterminator": "\n",
    }


def iter_csv(path: str, dialect: dict):
    """Yield (line_number, row) for each data row; the header comes first."""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, **dialect)
        for row in reader:
            yield reader.line_num, row


def open_rows(path: str, dialect: dict):
    """Return (header, row_iterator); header is None for an empty file."""
    rows = iter_csv(path, dialect)
    for _line_no, header in rows:
        return header, rows
    return None, rows


def column_positions(header):
    """Map each column name to its first position in the header."""
    positions = {}
    for index, name in enumerate(header):
        positions.setdefault(name, index)
    return positions


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
            raise MergeError(f"cannot read schema file {spec!r}: {exc}") from None
    else:
        stripped = spec.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            text = spec
        else:
            raise MergeError(f"schema file not found: {spec}")

    try:
        document = json.loads(text)
    except ValueError as exc:
        raise MergeError(f"invalid schema JSON: {exc}") from None

    if isinstance(document, dict):
        columns = document.get("columns")
    elif isinstance(document, list):
        columns = document
    else:
        columns = None
    if not isinstance(columns, list):
        raise MergeError('schema must contain a "columns" array')

    names, types = [], []
    for entry in columns:
        if isinstance(entry, str):
            name, type_name = entry, "string"
        elif isinstance(entry, dict):
            name = entry.get("name")
            type_name = entry.get("type", "string")
        else:
            raise MergeError(f"invalid schema column entry: {entry!r}")
        if not isinstance(name, str) or not name:
            raise MergeError(f"invalid schema column name: {name!r}")
        if not isinstance(type_name, str):
            raise MergeError(f"invalid schema column type for {name!r}")
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
            raise MergeError(
                f"invalid type {type_name!r} for column {name!r}; "
                f"valid types: {', '.join(VALID_TYPES)}"
            )
        if name in names:
            continue  # first definition wins
        names.append(name)
        types.append(type_name)

    if not names:
        raise MergeError("schema contains no columns")
    return names, types


def infer_schema(paths, dialect: dict, mode: str, null_literal: str):
    """Infer output columns (lexicographic order) and their types."""
    all_names = set()
    per_file_types = {}   # column -> list of per-file resolved types (strict)
    global_obs = {}       # column -> ColumnObserver (loose)

    for path in paths:
        header, rows = open_rows(path, dialect)
        if header is None:
            continue
        all_names.update(header)
        positions = column_positions(header)

        file_obs = {name: ColumnObserver() for name in positions}
        single_column = len(header) == 1
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
                    continue  # nulls never influence inference
                if mode == "strict":
                    file_obs[name].observe(raw)
                else:
                    observer = global_obs.get(name)
                    if observer is None:
                        observer = global_obs[name] = ColumnObserver()
                    observer.observe(raw)

        if mode == "strict":
            for name, observer in file_obs.items():
                if observer.seen:
                    per_file_types.setdefault(name, []).append(observer.resolve())

    names = sorted(all_names)
    types = []
    for name in names:
        if mode == "strict":
            observed = per_file_types.get(name)
            if not observed:
                types.append("string")
            elif len(set(observed)) == 1:
                types.append(observed[0])
            else:
                types.append("string")  # conflicting types across files
        else:
            observer = global_obs.get(name)
            types.append(observer.resolve() if observer is not None else "string")
    return names, types


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

def build_records(paths, dialect, columns, types, key_indexes, args, sorter):
    """Read every input row, cast it to the resolved schema and feed the sorter."""
    null_literal = args.csv_null_literal
    on_error = args.on_type_error
    column_count = len(columns)
    sequence = 0

    for path in paths:
        header, rows = open_rows(path, dialect)
        if header is None:
            continue
        positions = column_positions(header)
        # Source index for every output column (-1 when the column is absent).
        source = [positions.get(name, -1) for name in columns]

        single_column = len(header) == 1
        for line_no, row in rows:
            if not row:
                if not single_column:
                    continue
                row = [""]
            width = len(row)
            out_row = [null_literal] * column_count
            sort_values = [NULL_SORT] * column_count

            for out_index in range(column_count):
                src = source[out_index]
                if src < 0 or src >= width:
                    continue
                raw = row[src]
                if raw == "" or raw == null_literal:
                    continue
                try:
                    sort_value, text = cast_cell(raw, types[out_index])
                except CastError:
                    if on_error == "fail":
                        raise MergeError(
                            f"{path}:{line_no}: cannot cast value {raw!r} in column "
                            f"{columns[out_index]!r} to type {types[out_index]}"
                        )
                    if on_error == "keep-string":
                        sort_value, text = (RANK_STR, raw), raw
                    else:  # coerce-null
                        continue
                out_row[out_index] = text
                sort_values[out_index] = sort_value

            composite = tuple(sort_values[i] for i in key_indexes)
            sorter.add((composite, sequence, tuple(out_row)))
            sequence += 1


def write_output(destination: str, columns, records):
    if destination == "-":
        stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        )
        close_stream = False
    else:
        stream = open(destination, "w", encoding="utf-8", newline="")
        close_stream = True

    try:
        writer = csv.writer(
            stream,
            delimiter=",",
            quotechar='"',
            doublequote=True,
            escapechar=None,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(columns)
        for record in records:
            writer.writerow(record[2])
        stream.flush()
    finally:
        if close_stream:
            stream.close()
        else:
            try:
                stream.detach()
            except Exception:
                pass


def _single_char(value: str, flag: str):
    if value is None:
        return None
    if value == "":
        return None
    if len(value) != 1:
        raise MergeError(f"{flag} must be a single character, got {value!r}")
    return value


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Merge multiple CSV files into one schema-aligned, sorted CSV.",
    )
    parser.add_argument("--output", required=True,
                        help="output CSV path, or '-' for stdout")
    parser.add_argument("--key", required=True, action="append",
                        help="sort key column(s); comma separated, may repeat")
    parser.add_argument("--desc", action="store_true",
                        help="sort all keys in descending order")
    parser.add_argument("--schema", default=None,
                        help="path to a JSON schema describing the output columns")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict",
                        help="schema inference mode when --schema is absent")
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
    parser.add_argument("inputs", nargs="+", metavar="INPUT.csv")
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
        raise MergeError("--key requires at least one column name")

    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise MergeError("--memory-limit-mb must be a positive integer")

    paths = list(args.inputs)
    for path in paths:
        if not os.path.isfile(path):
            raise MergeError(f"input file not found: {path}")

    dialect = read_dialect_kwargs(args)

    if args.schema:
        columns, types = load_schema(args.schema)
    else:
        columns, types = infer_schema(paths, dialect, args.infer, args.csv_null_literal)

    if not columns:
        raise MergeError("resolved schema has no columns")

    index_of = {name: i for i, name in enumerate(columns)}
    missing = [k for k in keys if k not in index_of]
    if missing:
        raise MergeError(
            "key column(s) not present in resolved schema: " + ", ".join(missing)
        )
    key_indexes = [index_of[k] for k in keys]

    budget = max(4 * 1024 * 1024, int(args.memory_limit_mb * 1024 * 1024 * 0.30))

    if args.temp_dir:
        os.makedirs(args.temp_dir, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="merge_files-", dir=args.temp_dir)

    def cleanup():
        shutil.rmtree(temp_dir, ignore_errors=True)

    atexit.register(cleanup)
    try:
        sorter = ExternalSorter(temp_dir, budget, args.desc)
        build_records(paths, dialect, columns, types, key_indexes, args, sorter)
        write_output(args.output, columns, sorter.sorted_records())
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
        return 1
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
        return 1


if __name__ == "__main__":
    sys.exit(main())

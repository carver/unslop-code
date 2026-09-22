#!/usr/bin/env python3
"""CSV Merger and Sorter.

Ingests multiple CSV files, aligns their schemas (provided or inferred),
casts cells to the resolved types and emits a single globally sorted CSV.

Sorting is done with an external merge sort so that inputs far larger than
``--memory-limit-mb`` can be processed.
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

EXIT_ERROR = 1


class UserError(Exception):
    """A user facing error; reported on stderr with a non-zero exit."""


# --------------------------------------------------------------------------
# CSV dialect handling
# --------------------------------------------------------------------------
def parse_line(line, quotechar, escapechar):
    """Split one physical CSV line into fields.

    Comma delimited, RFC-4180 quoting with doubled quotes, plus optional
    backslash style escapes inside quoted fields.  No multiline fields.
    """
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


def iter_csv(path, quotechar, escapechar):
    """Yield ``(lineno, fields)`` for every non-empty line of *path*."""
    try:
        handle = open(path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc))
    with handle as fh:
        # A blank line is a real (all-null) single-column row, so only blank
        # lines trailing at end of file are dropped.
        pending = []
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if line.endswith("\r"):
                line = line[:-1]
            if line == "":
                pending.append(lineno)
                continue
            for blank in pending:
                yield blank, [""]
            pending = []
            yield lineno, parse_line(line, quotechar, escapechar)


def read_header(path, quotechar, escapechar):
    for _lineno, fields in iter_csv(path, quotechar, escapechar):
        return fields
    return []


def iter_data_rows(path, quotechar, escapechar):
    first = True
    for lineno, fields in iter_csv(path, quotechar, escapechar):
        if first:
            first = False
            continue
        yield lineno, fields


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
# Type inference
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


def best_type(candidates):
    for name in TYPE_PRIORITY:
        if name in candidates:
            return name
    return "string"


def header_index(header):
    """Map column name -> first index in *header*."""
    index = {}
    for pos, name in enumerate(header):
        if name not in index:
            index[name] = pos
    return index


def infer_schema(inputs, mode, quotechar, escapechar, null_literal):
    columns = set()
    per_file = {}
    global_inter = {}

    for path in inputs:
        header = read_header(path, quotechar, escapechar)
        index = header_index(header)
        columns.update(index)
        file_inter = {}
        for _lineno, fields in iter_data_rows(path, quotechar, escapechar):
            for name, pos in index.items():
                raw = fields[pos] if pos < len(fields) else ""
                is_null = raw == "" or raw == null_literal
                cand = candidate_types(raw)
                if mode == "strict":
                    prev = file_inter.get(name)
                    file_inter[name] = cand if prev is None else (prev & cand)
                else:
                    if is_null:
                        continue
                    prev = global_inter.get(name)
                    global_inter[name] = cand if prev is None else (prev & cand)
        if mode == "strict":
            for name, inter in file_inter.items():
                per_file.setdefault(name, set()).add(best_type(inter))

    resolved = []
    for name in sorted(columns):
        if mode == "strict":
            seen = per_file.get(name)
            if not seen or len(seen) != 1:
                col_type = "string"
            else:
                col_type = next(iter(seen))
        else:
            inter = global_inter.get(name)
            col_type = "string" if not inter else best_type(inter)
        resolved.append((name, col_type))
    return resolved


def load_schema(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        raise UserError("cannot read schema %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise UserError("invalid schema JSON in %s: %s" % (path, exc))
    if not isinstance(doc, dict) or not isinstance(doc.get("columns"), list):
        raise UserError("schema must be an object with a 'columns' list")
    resolved = []
    names = set()
    for entry in doc["columns"]:
        if not isinstance(entry, dict):
            raise UserError("each schema column must be an object")
        name = entry.get("name")
        col_type = entry.get("type", "string")
        if not isinstance(name, str) or name == "":
            raise UserError("schema column is missing a 'name'")
        if col_type not in VALID_TYPES:
            raise UserError(
                "unknown type %r for column %r (valid: %s)"
                % (col_type, name, ", ".join(VALID_TYPES))
            )
        if name in names:
            raise UserError("duplicate schema column %r" % name)
        names.add(name)
        resolved.append((name, col_type))
    return resolved


# --------------------------------------------------------------------------
# Records and ordering
# --------------------------------------------------------------------------
_DESC = False

NULL_KEY = (0, 0, "")


class Rec(object):
    __slots__ = ("key", "seq", "cells")

    def __init__(self, key, seq, cells):
        self.key = key
        self.seq = seq
        self.cells = cells

    def __lt__(self, other):
        if self.key != other.key:
            if _DESC:
                return self.key > other.key
            return self.key < other.key
        # Stable with respect to input appearance for equal keys.
        return self.seq < other.seq


def cast_cell(raw, col_type, on_type_error, null_literal, where):
    """Return ``(output_text, key_component)`` for one cell."""
    if raw == "" or raw == null_literal:
        return null_literal, NULL_KEY
    try:
        value = PARSERS[col_type](raw)
    except ValueError:
        if on_type_error == "fail":
            raise UserError(
                "cannot cast %r to %s (%s)" % (raw, col_type, where)
            )
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
            fh.write(json.dumps([rec.key, rec.seq, rec.cells]) + "\n")
    chunk_paths.append(path)
    records.clear()


def read_chunk(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            key, seq, cells = json.loads(line)
            yield Rec(tuple(tuple(part) for part in key), seq, cells)


def estimate_size(cells):
    total = 160
    for cell in cells:
        total += len(cell) + 56
    return total


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="merge_files.py",
        description="Merge multiple CSV files into one sorted CSV.",
    )
    parser.add_argument("--output", required=True,
                        help="output path, or - for stdout")
    parser.add_argument("--key", required=True, action="append",
                        help="comma separated sort key column(s)")
    parser.add_argument("--desc", action="store_true",
                        help="sort all keys descending")
    parser.add_argument("--schema", default=None,
                        help="path to a JSON schema file")
    parser.add_argument("--infer", choices=("strict", "loose"),
                        default="strict")
    parser.add_argument("--on-type-error",
                        choices=("coerce-null", "fail", "keep-string"),
                        default="coerce-null")
    parser.add_argument("--memory-limit-mb", type=int, default=64)
    parser.add_argument("--temp-dir", default=None)
    parser.add_argument("--csv-quotechar", default='"')
    parser.add_argument("--csv-escapechar", default="\\")
    parser.add_argument("--csv-null-literal", default="")
    parser.add_argument("inputs", nargs="+")
    return parser


def resolve_keys(key_args, schema):
    keys = []
    for chunk in key_args:
        for part in chunk.split(","):
            name = part.strip()
            if name == "":
                raise UserError("empty key column name")
            if name not in keys:
                keys.append(name)
    names = [name for name, _ in schema]
    for name in keys:
        if name not in names:
            raise UserError("key column %r is not present in the resolved schema" % name)
    return keys


def run(args):
    global _DESC
    _DESC = bool(args.desc)

    quotechar = args.csv_quotechar
    if len(quotechar) != 1:
        raise UserError("--csv-quotechar must be a single character")
    escapechar = args.csv_escapechar
    if len(escapechar) > 1:
        raise UserError("--csv-escapechar must be a single character")
    if escapechar == "":
        escapechar = None
    null_literal = args.csv_null_literal

    for path in args.inputs:
        if not os.path.isfile(path):
            raise UserError("input file not found: %s" % path)

    if args.schema:
        schema = load_schema(args.schema)
    else:
        schema = infer_schema(args.inputs, args.infer, quotechar, escapechar,
                              null_literal)

    keys = resolve_keys(args.key, schema)
    col_names = [name for name, _ in schema]
    col_types = [ctype for _, ctype in schema]
    key_positions = [col_names.index(name) for name in keys]
    col_to_slots = {}
    for slot, kpos in enumerate(key_positions):
        col_to_slots.setdefault(kpos, []).append(slot)

    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise UserError("--memory-limit-mb must be positive")
    budget = max(int(args.memory_limit_mb * 1024 * 1024 * 0.25), 65536)

    temp_parent = args.temp_dir
    if temp_parent:
        try:
            os.makedirs(temp_parent, exist_ok=True)
        except OSError as exc:
            raise UserError("cannot use --temp-dir %s: %s" % (temp_parent, exc))
    temp_dir = tempfile.mkdtemp(prefix="merge_files_", dir=temp_parent)

    chunk_paths = []
    buffer = []
    used = 0
    seq = 0
    try:
        for path in args.inputs:
            header = read_header(path, quotechar, escapechar)
            index = header_index(header)
            positions = [index.get(name) for name in col_names]
            for lineno, fields in iter_data_rows(path, quotechar, escapechar):
                cells = []
                key_parts = [None] * len(key_positions)
                for col, pos in enumerate(positions):
                    if pos is None or pos >= len(fields):
                        raw = ""
                    else:
                        raw = fields[pos]
                    where = "%s:%d column %r" % (path, lineno, col_names[col])
                    text, keypart = cast_cell(
                        raw, col_types[col], args.on_type_error,
                        null_literal, where)
                    cells.append(text)
                    for slot in col_to_slots.get(col, ()):
                        key_parts[slot] = keypart
                buffer.append(Rec(tuple(key_parts), seq, cells))
                seq += 1
                used += estimate_size(cells)
                if used >= budget:
                    spill(buffer, temp_dir, chunk_paths)
                    used = 0

        if chunk_paths and buffer:
            spill(buffer, temp_dir, chunk_paths)
            used = 0

        if chunk_paths:
            streams = [read_chunk(p) for p in chunk_paths]
            ordered = heapq.merge(*streams)
        else:
            buffer.sort()
            ordered = iter(buffer)

        if args.output == "-":
            out = sys.stdout
            close_out = False
        else:
            try:
                out = open(args.output, "w", encoding="utf-8", newline="")
            except OSError as exc:
                raise UserError("cannot write output %s: %s"
                                % (args.output, exc))
            close_out = True
        try:
            writer = csv.writer(out, delimiter=",", quotechar='"',
                                doublequote=True, escapechar=None,
                                quoting=csv.QUOTE_MINIMAL,
                                lineterminator="\n")
            writer.writerow(col_names)
            for rec in ordered:
                writer.writerow(rec.cells)
            out.flush()
        finally:
            if close_out:
                out.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except UserError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR
    except BrokenPipeError:
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

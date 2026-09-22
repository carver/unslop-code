#!/usr/bin/env python3
"""Merge heterogeneous tabular inputs into one schema-aligned, sorted CSV.

Accepts CSV, TSV, JSON Lines and Parquet sources (optionally gzip-compressed),
reconciles their schemas, casts every cell to the resolved type and emits a
single globally sorted CSV. A provided schema may declare nested columns
(struct, array<T>, map<string,T>, or the `json` wildcard); those are cast
recursively and written as canonical JSON in their CSV cell, and --key and
--partition-by accept dotted/bracketed field paths into them.

See AMBIGUITIES.md for the interpretation chosen wherever the spec left room.
"""

import argparse
import atexit
import collections
import contextlib
import csv
import gzip
import heapq
import io
import json
import os
import re
import shutil
import string
import sys
import tempfile
import zlib
from collections import Counter
from datetime import date, datetime, timezone
from functools import cmp_to_key

PROG = "merge_files.py"

# Exit codes (T26): the spec pins 2, 3, 5 and 6; 1 and 4 fill the gaps.
EXIT_IO = 1
EXIT_USAGE = 2
EXIT_SCHEMA = 3
EXIT_CAST = 4
EXIT_DATA = 5
EXIT_NESTED = 6

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

# JSON numbers outside this range cannot be "int ... within range" (T36).
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

EXT_FORMATS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}

# Precedence for --schema-strategy=authoritative: the more type information a
# format carries, the lower (stronger) its rank (T31).
FORMAT_PRECEDENCE = {"parquet": 0, "jsonl": 1, "tsv": 2, "csv": 2}

DEFAULT_ROW_GROUP_BYTES = 8 * 1024 * 1024

# Rows converted to Python dicts at a time, whatever the batch size.
PARQUET_PYLIST_CHUNK = 2048

MISSING = object()

# The exact wording the spec pins for nested input without a provided schema.
NESTED_MESSAGE = "ERR 6 nested structure requires provided --schema"


class Fatal(Exception):
    """An error reported on stderr with a specific exit code."""

    def __init__(self, message, code=EXIT_IO):
        super().__init__(message)
        self.code = code


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


def value_bits(value, is_text):
    """Inference candidates for one observed value.

    Text cells (CSV/TSV) and JSON strings are inferred from their text; JSON
    numbers and booleans carry their own type and are never re-read as
    something narrower (T35).
    """
    if is_text or isinstance(value, str):
        return candidate_bits(value)
    if isinstance(value, bool):
        return BIT["bool"] | BIT["string"]
    if isinstance(value, int):
        return BIT["int"] | BIT["float"] | BIT["string"]
    if isinstance(value, float):
        return BIT["float"] | BIT["string"]
    return candidate_bits(native_text(value))


def declared_bits(typ):
    """Inference candidates implied by a declared (Parquet) column type."""
    if typ == "string":
        return BIT["string"]
    return BIT[typ] | BIT["string"]


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


def native_text(value):
    """Canonical text for a value that arrived already typed (T37)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return render_timestamp(value.astimezone(timezone.utc))
    if isinstance(value, date):
        return render("date", value)
    return str(value)


def normalize_json_number(value):
    """JSON numbers prefer int when integral and within 64-bit range (T36)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if INT64_MIN <= value <= INT64_MAX else float(value)
    if isinstance(value, float):
        if value.is_integer() and INT64_MIN <= value <= INT64_MAX:
            return int(value)
        return value
    return value


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
# Nested type model
# --------------------------------------------------------------------------

# The wildcard kind: `json` (and a bare `struct`/`array`/`map`) accepts any
# JSON value, casts nothing and is re-emitted as canonical JSON (T65).
JSON_TYPE = "json"
CONSTRUCTORS = ("struct", "array", "map")


class Raw(str):
    """Text kept verbatim by --on-type-error=keep-string."""

    __slots__ = ()


class StructType:
    kind = "struct"
    __slots__ = ("fields", "index")

    def __init__(self, fields):
        self.fields = fields                       # [(name, type)] declared order
        self.index = dict(fields)


class ArrayType:
    kind = "array"
    __slots__ = ("element",)

    def __init__(self, element):
        self.element = element


class MapType:
    kind = "map"
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def is_primitive(typ):
    return isinstance(typ, str) and typ in VALID_TYPES


def type_name(typ):
    if isinstance(typ, str):
        return typ
    if typ.kind == "struct":
        return "struct"
    if typ.kind == "array":
        return "array<%s>" % type_name(typ.element)
    return "map<string,%s>" % type_name(typ.value)


# --------------------------------------------------------------------------
# Type aliases
# --------------------------------------------------------------------------

BUILTIN_ALIASES = {
    "integer": "int",
    "long": "int",
    "double": "float",
    "number": "float",
    "boolean": "bool",
    "datetime": "timestamp",
    "timestamptz": "timestamp",
    "text": "string",
    "varchar": "string",
    "list": "array",
    "json": "struct",
}


def split_generic(text, code):
    """`array<int>` -> ("array", ["int"]); a bare name -> (name, None)."""
    start = text.find("<")
    if start < 0:
        return text, None
    if not text.endswith(">"):
        raise Fatal(f"malformed type {text!r}", code)
    head = text[:start].strip()
    body = text[start + 1:-1]
    args, depth, cur = [], 0, []
    for ch in body:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    args.append("".join(cur))
    if depth != 0:
        raise Fatal(f"malformed type {text!r}", code)
    return head, [a.strip() for a in args]


class AliasTable:
    """Case-insensitive, transitive, cycle-checked type-name resolution."""

    def __init__(self, user=None):
        self.map = dict(BUILTIN_ALIASES)
        self.user = dict(user or {})
        # A user entry may shadow a built-in alias, but never a primitive name:
        # the six primitives are the terminals of resolution (T69).
        self.map.update(self.user)

    # -- alias chasing ----------------------------------------------------

    def _chase(self, name, stack, code):
        """Follow `name` through the alias map to a terminal type text.

        Returns (terminal_text, names_traversed). A terminal is a primitive,
        a bare constructor, or any parameterized (`...<...>`) spelling.
        """
        seen = list(stack)
        traversed = []
        cur = name
        while True:
            if cur in VALID_TYPES or cur in CONSTRUCTORS or "<" in cur:
                return cur, traversed
            if cur in seen:
                raise Fatal(f"type alias cycle involving {cur!r}", EXIT_USAGE)
            target = self.map.get(cur)
            if target is None:
                raise Fatal(
                    f"unknown type {cur!r}; valid types are "
                    f"{', '.join(sorted(VALID_TYPES))}, json, struct, array, map "
                    f"and any declared alias", code)
            seen.append(cur)
            traversed.append(cur)
            cur = target.strip().lower()

    # -- resolution -------------------------------------------------------

    def resolve(self, spec, code=EXIT_SCHEMA, stack=()):
        if isinstance(spec, str):
            return self._resolve_text(spec, code, stack)
        if isinstance(spec, dict):
            return self._resolve_object(spec, code, stack)
        raise Fatal(f"invalid type declaration {spec!r}", code)

    def _resolve_text(self, text, code, stack):
        low = text.strip().lower()
        if not low:
            raise Fatal("empty type name", code)
        term, traversed = self._chase(low, stack, code)
        stack = tuple(stack) + tuple(traversed)
        head, args = split_generic(term, code)
        if args is None:
            if head in VALID_TYPES:
                return head
            return JSON_TYPE                       # bare struct/array/map/json
        kind, more = self._chase(head, stack, code)
        stack = stack + tuple(more)
        return self._build(kind, args, None, code, stack, text)

    def _resolve_object(self, obj, code, stack):
        if len(obj) != 1:
            raise Fatal(
                "a nested type must be a JSON object with exactly one of "
                '"struct", "array" or "map"', code)
        key, body = next(iter(obj.items()))
        if not isinstance(key, str):
            raise Fatal("type constructor names must be strings", code)
        kind, traversed = self._chase(key.strip().lower(), stack, code)
        stack = tuple(stack) + tuple(traversed)
        if kind not in CONSTRUCTORS:
            raise Fatal(f"unknown nested type constructor {key!r}", code)
        return self._build(kind, None, body, code, stack, key)

    def _build(self, kind, args, body, code, stack, where):
        if kind == "struct":
            if args is not None:
                raise Fatal(
                    f"struct must be declared with named fields, not {where!r}",
                    code)
            return self._struct(body, code, stack)
        if kind == "array":
            if args is not None:
                if len(args) != 1:
                    raise Fatal(f"array takes exactly one element type: "
                                f"{where!r}", code)
                element = args[0]
            elif isinstance(body, dict) and "element" in body:
                element = body["element"]
            else:
                element = body if body is not None else "string"
            return ArrayType(self.resolve(element, code, stack))
        # map
        if args is not None:
            if len(args) != 2:
                raise Fatal(f"map takes a key and a value type: {where!r}", code)
            key_spec, value_spec = args
        elif isinstance(body, dict) and ("key" in body or "value" in body):
            key_spec = body.get("key", "string")
            value_spec = body.get("value", "string")
        else:
            key_spec = "string"
            value_spec = body if body is not None else "string"
        key_type = self.resolve(key_spec, code, stack)
        if key_type != "string":
            raise Fatal("map keys must be of type string", code)
        return MapType(self.resolve(value_spec, code, stack))

    def _struct(self, body, code, stack):
        fields_spec = body.get("fields") if isinstance(body, dict) else body
        if not isinstance(fields_spec, list):
            raise Fatal('a struct type needs a "fields" array', code)
        fields = []
        seen = set()
        for entry in fields_spec:
            if not isinstance(entry, dict) or "name" not in entry:
                raise Fatal('each struct field needs a "name"', code)
            name = entry["name"]
            if not isinstance(name, str):
                raise Fatal("struct field names must be strings", code)
            if name in seen:
                raise Fatal(f"duplicate struct field {name!r}", code)
            seen.add(name)
            fields.append((name, self.resolve(entry.get("type", "string"),
                                              code, stack)))
        return StructType(fields)

    def validate(self):
        """Resolve every user alias eagerly: cycles and dangling names now (T68)."""
        for name in self.user:
            self.resolve(name, EXIT_USAGE)


def load_alias_table(spec):
    """Build the alias table from --type-alias-file (a path or literal JSON)."""
    if spec is None:
        return AliasTable()
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise Fatal(f"cannot read type alias file {spec}: {exc}", EXIT_IO)
    elif spec.lstrip().startswith("{"):
        text = spec
    else:
        raise Fatal(f"cannot read type alias file {spec}: no such file", EXIT_IO)
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise Fatal(f"invalid type alias JSON: {exc}", EXIT_USAGE)
    if not isinstance(doc, dict) or not isinstance(doc.get("aliases"), dict):
        raise Fatal('type alias file must be a JSON object with an "aliases" '
                    "object", EXIT_USAGE)
    user = {}
    for name, target in doc["aliases"].items():
        if not isinstance(name, str) or not isinstance(target, str):
            raise Fatal("type aliases must map strings to strings", EXIT_USAGE)
        user[name.strip().lower()] = target.strip().lower()
    table = AliasTable(user)
    table.validate()
    return table


# --------------------------------------------------------------------------
# Field paths
# --------------------------------------------------------------------------

INDEX_RE = re.compile(r"^\d+$")


def err3(role, path):
    return f'ERR 3 {role} column "{path}" does not resolve to a primitive'


def parse_field_path(text, role):
    """`items.0.sku` / `attrs["country"]` -> a list of path segments (T76)."""
    bad = Fatal(err3(role, text), EXIT_SCHEMA)
    segments = []
    buf = []
    i = 0
    size = len(text)

    def flush():
        if buf:
            segments.append(("token", "".join(buf)))
            del buf[:]

    while i < size:
        ch = text[i]
        if ch == ".":
            if not buf and not segments:
                raise bad
            flush()
            i += 1
        elif ch == "[":
            flush()
            if not segments:
                raise bad
            j = i + 1
            if j < size and text[j] in "\"'":
                quote = text[j]
                j += 1
                out = []
                while j < size and text[j] != quote:
                    if text[j] == "\\" and j + 1 < size:
                        j += 1
                    out.append(text[j])
                    j += 1
                if j >= size:
                    raise bad
                j += 1
                if j >= size or text[j] != "]":
                    raise bad
                segments.append(("key", "".join(out)))
                i = j + 1
            else:
                end = text.find("]", j)
                if end < 0:
                    raise bad
                inner = text[j:end].strip()
                if INDEX_RE.match(inner):
                    segments.append(("token", inner))
                else:
                    segments.append(("key", inner))
                i = end + 1
        else:
            buf.append(ch)
            i += 1
    flush()
    if not segments or segments[0][0] != "token" or segments[0][1] == "":
        raise bad
    return segments


class FieldPath:
    """A compiled --key / --partition-by path into one output column."""

    __slots__ = ("text", "column", "accessors", "type")

    def __init__(self, text, column, accessors, typ):
        self.text = text
        self.column = column
        self.accessors = accessors
        self.type = typ


def path_root(text, names, role="key"):
    """The output column a path starts at, or None when there is none (T77)."""
    if text in names:
        return text
    try:
        segments = parse_field_path(text, role)
    except Fatal:
        return None
    root = segments[0][1]
    return root if root in names else None


def compile_field_path(text, names, types, role):
    """Resolve `text` against the declared schema; must land on a primitive."""
    if text in names:
        index = names.index(text)
        typ = types[index]
        if not is_primitive(typ):
            raise Fatal(err3(role, text), EXIT_SCHEMA)
        return FieldPath(text, index, (), typ)

    segments = parse_field_path(text, role)
    index = names.index(segments[0][1])
    typ = types[index]
    accessors = []
    for kind, token in segments[1:]:
        if isinstance(typ, StructType):
            if token not in typ.index:
                raise Fatal(err3(role, text), EXIT_SCHEMA)
            accessors.append(("field", token))
            typ = typ.index[token]
        elif isinstance(typ, ArrayType):
            # Array indices must be non-negative integers (T79).
            if not INDEX_RE.match(token):
                raise Fatal(err3(role, text), EXIT_SCHEMA)
            accessors.append(("index", int(token)))
            typ = typ.element
        elif isinstance(typ, MapType):
            accessors.append(("key", token))
            typ = typ.value
        else:
            # A primitive leaf, or the `json` wildcard whose shape is unknown
            # and so can never be *proved* to reach a primitive (T80).
            raise Fatal(err3(role, text), EXIT_SCHEMA)
    if not is_primitive(typ):
        raise Fatal(err3(role, text), EXIT_SCHEMA)
    return FieldPath(text, index, tuple(accessors), typ)


def walk_path(tree, accessors):
    """Follow a compiled path through one row's cast value tree."""
    cur = tree
    for kind, arg in accessors:
        if cur is None:
            return None
        if kind == "index":
            if not isinstance(cur, list) or arg >= len(cur):
                return None
            cur = cur[arg]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(arg)
    return cur


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
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
    )
    p.add_argument("--output", required=True, metavar="PATH|-",
                   help="output CSV path, or - for stdout")
    p.add_argument("--key", required=True, action="append",
                   metavar="FIELDPATH[,FIELDPATH...]",
                   help="sort key field path(s) such as user.id, items.0.sku or "
                        'attrs["country"]; may be repeated or comma-separated')
    p.add_argument("--desc", action="store_true",
                   help="sort all key columns in descending order")
    p.add_argument("--partition-by", dest="partition_by", action="append",
                   metavar="FIELDPATH[,FIELDPATH...]",
                   help="Hive-style partition field path(s); may be repeated")
    p.add_argument("--max-rows-per-file", dest="max_rows_per_file", type=int,
                   metavar="INT",
                   help="cut each output file after this many data rows")
    p.add_argument("--max-bytes-per-file", dest="max_bytes_per_file", type=int,
                   metavar="INT",
                   help="cut each output file at this many bytes on disk")
    p.add_argument("--schema", metavar="SCHEMA_JSON",
                   help="path to a JSON schema document (or literal JSON)")
    p.add_argument("--type-alias-file", dest="type_alias_file",
                   metavar="ALIASES_JSON",
                   help="path to a JSON type-alias document (or literal JSON)")
    p.add_argument("--infer", choices=("strict", "loose"), default="strict",
                   help="type inference mode when no schema is given")
    p.add_argument("--schema-strategy", dest="schema_strategy",
                   choices=("authoritative", "consensus", "union"),
                   default="authoritative",
                   help="how to resolve conflicting types across inputs")
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
    p.add_argument("--input-format", dest="input_format",
                   choices=("auto", "csv", "tsv", "jsonl", "parquet"), default="auto",
                   help="force the format of every input instead of detecting it")
    p.add_argument("--compression", choices=("auto", "none", "gzip"), default="auto",
                   help="force the compression of every input")
    p.add_argument("--parquet-row-group-bytes", type=int,
                   dest="parquet_row_group_bytes", default=DEFAULT_ROW_GROUP_BYTES,
                   help="advisory batch size, in bytes, for Parquet reads")
    p.add_argument("inputs", nargs="+", metavar="INPUT")
    return p


def parse_args(argv):
    args = build_parser().parse_args(argv)
    keys = []
    for spec in args.key:
        for name in spec.split(","):
            keys.append(name.strip())
    if not keys or any(k == "" for k in keys):
        raise Fatal("--key must name at least one column", EXIT_USAGE)
    args.keys = keys
    if args.memory_limit_mb <= 0:
        raise Fatal("--memory-limit-mb must be a positive integer", EXIT_USAGE)
    if args.parquet_row_group_bytes <= 0:
        raise Fatal("--parquet-row-group-bytes must be a positive integer",
                    EXIT_USAGE)

    # Partitioning (T56: comma lists and repeated flags, order preserved).
    partition = []
    for spec in (args.partition_by or ()):
        for name in spec.split(","):
            partition.append(name.strip())
    if args.partition_by is not None and (not partition or "" in partition):
        raise Fatal("--partition-by must name at least one column", EXIT_USAGE)
    args.partition = partition

    # T55: a limit of zero (or less) cannot be honoured by any output file.
    if args.max_rows_per_file is not None and args.max_rows_per_file <= 0:
        raise Fatal("--max-rows-per-file must be a positive integer", EXIT_USAGE)
    if args.max_bytes_per_file is not None and args.max_bytes_per_file <= 0:
        raise Fatal("--max-bytes-per-file must be a positive integer", EXIT_USAGE)

    args.partitioned = bool(partition
                            or args.max_rows_per_file is not None
                            or args.max_bytes_per_file is not None)
    if args.partitioned and args.output == "-":
        # T50: an argument-only conflict, decidable before reading anything.
        raise Fatal("--output must be a directory path (not -) when "
                    "--partition-by, --max-rows-per-file or "
                    "--max-bytes-per-file is given", EXIT_USAGE)
    return args


# --------------------------------------------------------------------------
# Input detection
# --------------------------------------------------------------------------

@contextlib.contextmanager
def read_guard(path):
    """Translate reader exceptions into Fatal with the right exit code."""
    try:
        yield
    except Fatal:
        raise
    except UnicodeDecodeError as exc:
        raise Fatal(f"{path} is not valid UTF-8: {exc}", EXIT_DATA)
    except (gzip.BadGzipFile, zlib.error, EOFError) as exc:
        raise Fatal(f"cannot decompress {path}: {exc}", EXIT_DATA)
    except csv.Error as exc:
        raise Fatal(f"malformed delimited text in {path}: {exc}", EXIT_DATA)
    except OSError as exc:
        raise Fatal(f"cannot read input {path}: {exc}", EXIT_IO)


def read_magic(path, size=8):
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except OSError as exc:
        raise Fatal(f"cannot read input {path}: {exc}", EXIT_IO)


def peek_decompressed(path, compression, size=8):
    if compression != "gzip":
        return read_magic(path, size)
    with read_guard(path):
        with gzip.open(path, "rb") as fh:
            return fh.read(size)


def resolve_compression(path, flag):
    """Decide gzip vs none, and reject a resolution the bytes contradict."""
    actually_gzip = read_magic(path, 2).startswith(GZIP_MAGIC)
    if flag == "auto":
        chosen = "gzip" if path.lower().endswith(".gz") else "none"
    else:
        chosen = flag
    if (chosen == "gzip") != actually_gzip:
        want = "gzip-compressed" if chosen == "gzip" else "uncompressed"
        raise Fatal(
            f"compression mismatch for {path}: expected {want} data", EXIT_DATA
        )
    return chosen


def resolve_format(path, flag, compression):
    if flag != "auto":
        return flag
    base = path
    if base.lower().endswith(".gz"):
        base = base[:-3]
    ext = os.path.splitext(base)[1].lower()
    fmt = EXT_FORMATS.get(ext)
    if fmt is not None:
        return fmt
    if peek_decompressed(path, compression, 4) == PARQUET_MAGIC:
        return "parquet"
    raise Fatal(
        f"cannot determine input format for {path}: unrecognized extension "
        f"and no Parquet magic bytes", EXIT_USAGE
    )


# --------------------------------------------------------------------------
# Sources
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


def header_pairs(header):
    """(name, index) for each column, first occurrence of a name winning."""
    seen = set()
    pairs = []
    for i, name in enumerate(header):
        if name not in seen:
            seen.add(name)
            pairs.append((name, i))
    return pairs


class TextSource:
    """A CSV or TSV file; every value is raw text."""

    is_text = True
    allow_nested = False

    def __init__(self, path, fmt, compression, dialect):
        self.path = path
        self.fmt = fmt
        self.compression = compression
        self.dialect = dialect
        self.precedence = FORMAT_PRECEDENCE[fmt]
        self._header = None

    def _open(self):
        try:
            raw = (gzip.open(self.path, "rb") if self.compression == "gzip"
                   else open(self.path, "rb"))
        except OSError as exc:
            raise Fatal(f"cannot read input {self.path}: {exc}", EXIT_IO)
        return io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")

    def _reader(self, fh):
        if self.fmt == "tsv":
            return csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        return self.dialect.reader(fh)

    def declared_types(self):
        return None

    def header(self):
        if self._header is None:
            self._header = []
            with read_guard(self.path):
                with self._open() as fh:
                    for row in self._reader(fh):
                        self._header = row
                        break
        return self._header

    def columns(self):
        return [name for name, _ in header_pairs(self.header())]

    def iter_records(self, wanted=None):
        pairs = header_pairs(self.header())
        width = len(self.header())
        with read_guard(self.path):
            with self._open() as fh:
                reader = self._reader(fh)
                first = True
                for row in reader:
                    if first:
                        first = False
                        continue
                    if self.fmt == "tsv" and len(row) > width:
                        raise Fatal(
                            f"{self.path}:{reader.line_num}: literal tab inside "
                            f"a TSV field", EXIT_DATA
                        )
                    size = len(row)
                    rec = {name: (row[i] if i < size else "") for name, i in pairs}
                    yield (self.path, reader.line_num), rec


class JsonlSource:
    """A JSON Lines file; values arrive with their JSON types."""

    is_text = False
    fmt = "jsonl"
    allow_nested = False

    def __init__(self, path, compression):
        self.path = path
        self.compression = compression
        self.precedence = FORMAT_PRECEDENCE["jsonl"]

    def _open(self):
        try:
            raw = (gzip.open(self.path, "rb") if self.compression == "gzip"
                   else open(self.path, "rb"))
        except OSError as exc:
            raise Fatal(f"cannot read input {self.path}: {exc}", EXIT_IO)
        return io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")

    def declared_types(self):
        return None

    def columns(self):
        return []  # no header: field names come from the records themselves

    def iter_records(self, wanted=None):
        with read_guard(self.path):
            with self._open() as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue  # blank/whitespace lines ignored
                    where = (self.path, lineno)
                    try:
                        obj = json.loads(stripped)
                    except ValueError as exc:
                        raise Fatal(f"{self.path}:{lineno}: invalid JSON: {exc}",
                                    EXIT_DATA)
                    if not isinstance(obj, dict):
                        raise Fatal(
                            f"{self.path}:{lineno}: JSONL records must be JSON "
                            f"objects", EXIT_NESTED)
                    rec = {}
                    for name, value in obj.items():
                        if isinstance(value, (dict, list)):
                            # Nested input needs a schema that declares it (T90).
                            if not self.allow_nested:
                                raise Fatal(NESTED_MESSAGE, EXIT_NESTED)
                            rec[name] = value
                            continue
                        rec[name] = normalize_json_number(value)
                    yield where, rec


def import_parquet():
    try:
        import pyarrow.parquet as pq
        import pyarrow.types as patypes
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise Fatal(
            f"reading Parquet input requires the 'pyarrow' package: {exc}", EXIT_IO
        )
    return pq, patypes


def arrow_plain(value, arrow_type):
    """Turn one Arrow-decoded value into plain JSON-ish Python objects.

    `to_pylist` renders a map as a list of `(key, value)` tuples, which is not
    what a `map<string,T>` cast expects, and nested children need the same
    treatment recursively.
    """
    if value is None:
        return None
    _, patypes = import_parquet()
    if patypes.is_map(arrow_type):
        item = arrow_type.item_type
        out = {}
        for pair in value:
            if isinstance(pair, tuple):
                key, inner = pair
            elif isinstance(pair, dict):
                key, inner = pair.get("key"), pair.get("value")
            else:  # pragma: no cover - defensive
                continue
            # A JSON object cannot have a non-string key, so render it (T75).
            out[key if isinstance(key, str) else native_text(key)] = \
                arrow_plain(inner, item)
        return out
    if patypes.is_list(arrow_type) or patypes.is_large_list(arrow_type) \
            or patypes.is_fixed_size_list(arrow_type):
        element = arrow_type.value_type
        return [arrow_plain(v, element) for v in value]
    if patypes.is_struct(arrow_type):
        out = {}
        for field in arrow_type:
            out[field.name] = arrow_plain(value.get(field.name), field.type)
        return out
    return value


class ParquetSource:
    """A Parquet file, read one row-group batch at a time."""

    is_text = False
    fmt = "parquet"
    allow_nested = False

    def __init__(self, path, compression, args, store):
        self.path = path
        self.compression = compression
        self.args = args
        self.store = store
        self.precedence = FORMAT_PRECEDENCE["parquet"]
        self._local = None
        self._types = None
        self._names = None
        self._arrow = None

    def _local_path(self):
        if self._local is None:
            if self.compression == "gzip":
                self._local = self.store.decompress(self.path)
            else:
                self._local = self.path
        return self._local

    def _file(self):
        pq, _ = import_parquet()
        path = self._local_path()
        try:
            return pq.ParquetFile(path)
        except Fatal:
            raise
        except Exception as exc:
            raise Fatal(f"cannot read Parquet input {self.path}: {exc}", EXIT_DATA)

    def _map_type(self, patypes, arrow_type):
        if patypes.is_boolean(arrow_type):
            return "bool"
        if patypes.is_integer(arrow_type):
            return "int"
        if patypes.is_floating(arrow_type) or patypes.is_decimal(arrow_type):
            return "float"
        if patypes.is_date(arrow_type):
            return "date"
        if patypes.is_timestamp(arrow_type):
            return "timestamp"
        return "string"

    def declared_types(self):
        """Flat column -> inferred type; nested columns need a schema (T90)."""
        if self._types is None:
            _, patypes = import_parquet()
            schema = self._file().schema_arrow
            types = {}
            arrow = {}
            order = []
            for field in schema:
                if field.name in order:
                    continue  # first occurrence of a duplicated name wins
                nested = (patypes.is_nested(field.type)
                          or patypes.is_union(field.type))
                if nested and not self.allow_nested:
                    raise Fatal(NESTED_MESSAGE, EXIT_NESTED)
                if not nested:
                    types[field.name] = self._map_type(patypes, field.type)
                arrow[field.name] = field.type
                order.append(field.name)
            self._types = types
            self._arrow = arrow
            self._names = order
        return self._types

    def columns(self):
        self.declared_types()
        return list(self._names)

    def _batch_rows(self, pfile):
        """Turn the advisory byte budget into a row count (T39)."""
        budget = min(
            self.args.parquet_row_group_bytes,
            max(self.args.memory_limit_mb * 1024 * 1024 // 4, 64 * 1024),
        )
        meta = pfile.metadata
        avg = 1.0
        if meta is not None and meta.num_rows:
            total = sum(meta.row_group(i).total_byte_size
                        for i in range(meta.num_row_groups))
            avg = max(1.0, total / meta.num_rows)
        return max(1, min(int(budget // avg) or 1, 65536))

    def iter_records(self, wanted=None):
        self.declared_types()
        pfile = self._file()
        cols = [n for n in self._names if wanted is None or n in wanted]
        if not cols:
            total = pfile.metadata.num_rows if pfile.metadata else 0
            for index in range(total):
                yield (self.path, index + 1), {}
            return
        rows = self._batch_rows(pfile)
        chunk = min(rows, PARQUET_PYLIST_CHUNK)
        # Arrow renders maps as [(key, value)] pairs; rebuild them as objects.
        nested_cols = [n for n in cols if n not in self._types]
        index = 0
        try:
            batches = pfile.iter_batches(batch_size=rows, columns=cols)
            for batch in batches:
                # Materialize Python objects a slice at a time: a row group may
                # hold far more rows than the memory budget allows as dicts.
                for start in range(0, batch.num_rows, chunk):
                    for rec in batch.slice(start, chunk).to_pylist():
                        index += 1
                        if nested_cols:
                            for name in nested_cols:
                                rec[name] = arrow_plain(rec.get(name),
                                                        self._arrow[name])
                        yield (self.path, index), rec
        except Fatal:
            raise
        except Exception as exc:
            raise Fatal(f"cannot read Parquet input {self.path}: {exc}", EXIT_DATA)


def build_sources(args, dialect, store):
    sources = []
    for path in args.inputs:
        if not os.path.exists(path):
            raise Fatal(f"input file not found: {path}", EXIT_IO)
        compression = resolve_compression(path, args.compression)
        fmt = resolve_format(path, args.input_format, compression)
        if fmt == "parquet":
            sources.append(ParquetSource(path, compression, args, store))
        elif fmt == "jsonl":
            sources.append(JsonlSource(path, compression))
        else:
            sources.append(TextSource(path, fmt, compression, dialect))
    return sources


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

def load_schema_document(spec, aliases):
    text = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise Fatal(f"cannot read schema {spec}: {exc}", EXIT_IO)
    else:
        text = spec
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise Fatal(f"invalid schema JSON: {exc}", EXIT_SCHEMA)
    if not isinstance(doc, dict) or not isinstance(doc.get("columns"), list):
        raise Fatal('schema must be a JSON object with a "columns" array',
                    EXIT_SCHEMA)
    names, types = [], []
    for entry in doc["columns"]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise Fatal('each schema column needs a "name"', EXIT_SCHEMA)
        name = entry["name"]
        if not isinstance(name, str):
            raise Fatal("schema column names must be strings", EXIT_SCHEMA)
        typ = aliases.resolve(entry.get("type", "string"), EXIT_SCHEMA)
        if name in names:
            raise Fatal(f"duplicate column {name!r} in schema", EXIT_SCHEMA)
        names.append(name)
        types.append(typ)
    return names, types


def scan_source(source):
    """Per-column [bits, seen] evidence from one input."""
    info = {}
    declared = source.declared_types()
    if declared is not None:
        for name, typ in declared.items():
            info[name] = [declared_bits(typ), True]
        return info
    for name in source.columns():
        info.setdefault(name, [ALL_BITS, False])
    for _where, rec in source.iter_records():
        for name, value in rec.items():
            entry = info.get(name)
            if entry is None:
                entry = info[name] = [ALL_BITS, False]
            if value is None:
                continue
            if source.is_text and value == "":
                continue  # empty cells are nulls; they don't affect inference
            entry[1] = True
            if entry[0]:
                entry[0] &= value_bits(value, source.is_text)
    return info


def widen(group):
    merged = ALL_BITS
    for _src, bits, _typ in group:
        merged &= bits
    return best_type(merged)


def resolve_column(name, sources, infos, args):
    observed = []
    for source, info in zip(sources, infos):
        entry = info.get(name)
        if entry is None or not entry[1]:
            continue
        observed.append((source, entry[0], best_type(entry[0])))
    if not observed:
        return "string"

    strategy = args.schema_strategy
    if strategy == "union":
        group = observed
    elif strategy == "consensus":
        counts = Counter(typ for _s, _b, typ in observed)
        top = max(counts.values())
        tied = {typ for typ, count in counts.items() if count == top}
        if len(tied) == 1:
            return next(iter(tied))
        group = [o for o in observed if o[2] in tied]
    else:  # authoritative: only the most strongly typed sources get a say
        rank = min(source.precedence for source, _b, _t in observed)
        group = [o for o in observed if o[0].precedence == rank]

    types = {typ for _s, _b, typ in group}
    if len(types) == 1:
        return next(iter(types))
    if strategy != "authoritative" or args.infer == "loose":
        return widen(group)
    return "string"  # strict: conflicting types across files fall back to string


def infer_schema(sources, args):
    """Infer (names, types) from the union of every input's fields."""
    infos = []
    names = set()
    for source in sources:
        info = scan_source(source)
        infos.append(info)
        names.update(info)
    names = sorted(names)
    types = [resolve_column(name, sources, infos, args) for name in names]
    return names, types


# --------------------------------------------------------------------------
# Casting
# --------------------------------------------------------------------------

def json_text(obj):
    """Canonical JSON: minified, UTF-8 literal, RFC 8259 escaping (T86)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def plain_json(value):
    """A JSON-ready copy of a value accepted without casting (`json` type)."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, dict):
        return {(k if isinstance(k, str) else native_text(k)): plain_json(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json(v) for v in value]
    return native_text(value)


def stringify(value):
    """The text `keep-string` keeps, and the `<val>` an ERR 4 quotes (T73)."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return json_text(plain_json(value))
    if value is None:
        return "null"
    return native_text(value)


def jsonify(tree, typ):
    """Canonical JSON-ready form of a cast value tree."""
    if tree is None:
        return None
    if isinstance(tree, Raw):
        return str(tree)
    if isinstance(typ, StructType):
        return {name: jsonify(tree.get(name), ftype)
                for name, ftype in typ.fields}
    if isinstance(typ, ArrayType):
        return [jsonify(v, typ.element) for v in tree]
    if isinstance(typ, MapType):
        # Map keys sorted lexicographically.
        return {k: jsonify(tree[k], typ.value) for k in sorted(tree)}
    if typ == JSON_TYPE:
        # Unknown-keyed objects canonicalize like maps (T66).
        if isinstance(tree, dict):
            return {k: jsonify(tree[k], JSON_TYPE) for k in sorted(tree)}
        if isinstance(tree, list):
            return [jsonify(v, JSON_TYPE) for v in tree]
        return tree
    if typ == "date":
        return render("date", tree)
    if typ == "timestamp":
        return render_timestamp(tree)
    if isinstance(tree, float) and (tree != tree or abs(tree) == float("inf")):
        return None
    return tree


class Caster:
    """Casts one input value to its declared (possibly nested) type."""

    def __init__(self, names, types, on_type_error):
        self.names = names
        self.types = types
        self.on_type_error = on_type_error

    # -- failures ---------------------------------------------------------

    def _failed(self, value, typ, path, where):
        if self.on_type_error == "fail":
            raise Fatal(
                f'ERR 4 cannot cast "{stringify(value)}" to {type_name(typ)} '
                f'in field "{path}" (file={where[0]} line={where[1]})',
                EXIT_CAST,
            )
        if self.on_type_error == "keep-string":
            return Raw(stringify(value))
        return None

    def _parse_cell(self, text, typ, path, where):
        """A CSV/TSV cell must hold one JSON literal for a nested target."""
        try:
            return json.loads(text), True
        except ValueError:
            return self._failed(text, typ, path, where), False

    # -- casting ----------------------------------------------------------

    def node(self, value, typ, is_text, path, where):
        if value is MISSING or value is None:
            return None
        if is_text and value == "":
            return None                 # empty cell -> null, at any type

        if typ == JSON_TYPE:
            if is_text:
                value, ok = self._parse_cell(value, typ, path, where)
                if not ok:
                    return value
            return plain_json(value)

        if isinstance(typ, StructType):
            if is_text:
                value, ok = self._parse_cell(value, typ, path, where)
                if not ok:
                    return value
            if not isinstance(value, dict):
                return self._failed(value, typ, path, where)
            out = {}
            for name, ftype in typ.fields:
                out[name] = self.node(value.get(name, MISSING), ftype, False,
                                      f"{path}.{name}", where)
            return out

        if isinstance(typ, ArrayType):
            if is_text:
                value, ok = self._parse_cell(value, typ, path, where)
                if not ok:
                    return value
            if not isinstance(value, list):
                return self._failed(value, typ, path, where)
            return [self.node(v, typ.element, False, f"{path}.{i}", where)
                    for i, v in enumerate(value)]

        if isinstance(typ, MapType):
            if is_text:
                value, ok = self._parse_cell(value, typ, path, where)
                if not ok:
                    return value
            if not isinstance(value, dict):
                return self._failed(value, typ, path, where)
            out = {}
            for key, inner in value.items():
                key = key if isinstance(key, str) else native_text(key)
                out[key] = self.node(inner, typ.value, False,
                                     f'{path}["{key}"]', where)
            return out

        # primitive
        if isinstance(value, (dict, list)):
            return self._failed(value, typ, path, where)
        if is_text:
            text = value
        else:
            value = normalize_json_number(value)
            text = native_text(value)
        parsed = PARSERS[typ](text)
        if parsed is None:
            return self._failed(text, typ, path, where)
        return parsed

    def cast(self, value, is_text, col_index, where):
        """Cast one whole column value; returns its value tree (or None)."""
        return self.node(value, self.types[col_index], is_text,
                         self.names[col_index], where)

    def cell(self, tree, col_index):
        """The CSV cell content for a cast value tree (None -> null literal)."""
        if tree is None:
            return None
        if isinstance(tree, Raw):
            return str(tree)            # keep-string keeps the original text
        typ = self.types[col_index]
        if is_primitive(typ):
            return render(typ, tree)
        return json_text(jsonify(tree, typ))


def key_token(value, typ):
    """The sortable token for one resolved key/partition fragment."""
    if value is None:
        return None
    if isinstance(value, Raw):
        return [RANK_RAW, str(value)]
    return [RANK_VALUE, sort_payload(typ, value)]


def fragment_text(value, typ):
    """The partition-segment text for one resolved fragment."""
    if value is None:
        return None
    if isinstance(value, Raw):
        return str(value)
    return render(typ, value)


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
    """Holds sorted runs (and decompressed inputs) outside the heap."""

    def __init__(self, temp_dir):
        self.requested = temp_dir
        self.dir = None
        self.paths = []
        self.counter = 0
        if temp_dir is not None and not os.path.isdir(temp_dir):
            raise Fatal(f"--temp-dir {temp_dir} is not an existing directory",
                        EXIT_USAGE)
        atexit.register(self.cleanup)

    def _ensure_dir(self):
        if self.dir is None:
            try:
                self.dir = tempfile.mkdtemp(prefix="merge_files-", dir=self.requested)
            except OSError as exc:
                raise Fatal(f"cannot create temporary directory: {exc}", EXIT_IO)
        return self.dir

    def _new_path(self):
        self.counter += 1
        return os.path.join(self._ensure_dir(), f"run-{self.counter:08d}.jsonl")

    def decompress(self, path):
        """Materialize a gzip input so it can be read with random access."""
        self.counter += 1
        dest = os.path.join(self._ensure_dir(), f"input-{self.counter:08d}.bin")
        with read_guard(path):
            with gzip.open(path, "rb") as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
        return dest

    def _write_run(self, records):
        path = self._new_path()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, ensure_ascii=False))
                    fh.write("\n")
        except OSError as exc:
            raise Fatal(f"cannot write temporary file: {exc}", EXIT_IO)
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


def _json_lines(handle):
    for line in handle:
        if line:
            yield json.loads(line)


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def ingest(args, names, caster, store, sources, keys, partitions):
    """Read every input, cast cells, and produce sorted runs.

    Returns (in_memory_records, sort_key). When the store holds runs, the
    dataset lives on disk instead. Each record is
    `[key_tokens, sequence, cells, partition_fragments]`.
    """
    budget = max(int(args.memory_limit_mb * 1024 * 1024 * 0.6), 256 * 1024)
    compare = make_comparator(len(keys), args.desc)
    sort_key = cmp_to_key(compare)

    buffer = []
    used = 0
    seq = 0
    n_cols = len(names)
    wanted = set(names)

    # Columns a key or partition path reads: these are cast even when absent,
    # so a missing value still produces a (null) fragment.
    needed = {path.column for path in keys}
    needed.update(path.column for path in partitions)

    for source in sources:
        is_text = source.is_text
        for where, rec in source.iter_records(wanted=wanted):
            cells = [None] * n_cols
            trees = [None] * n_cols
            approx = ROW_OVERHEAD + 8 * n_cols + KEY_OVERHEAD * len(keys)
            for i in range(n_cols):
                value = rec.get(names[i], MISSING)
                if value is MISSING and i not in needed:
                    continue
                tree = caster.cast(value, is_text, i, where)
                trees[i] = tree
                out = caster.cell(tree, i)
                cells[i] = out
                if out is not None:
                    approx += len(out) + CELL_OVERHEAD
            tokens = [key_token(walk_path(trees[p.column], p.accessors), p.type)
                      for p in keys]
            parts = [fragment_text(walk_path(trees[p.column], p.accessors),
                                   p.type)
                     for p in partitions]
            buffer.append([tokens, seq, cells, parts])
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


@contextlib.contextmanager
def open_output(destination):
    """Yield a writable text stream; file destinations land atomically (T40)."""
    if destination == "-":
        stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="")
        try:
            yield stream
            stream.flush()
        finally:
            stream.detach()
        return

    directory = os.path.dirname(os.path.abspath(destination)) or "."
    try:
        fd, tmp = tempfile.mkstemp(prefix=".merge_files-", suffix=".tmp",
                                   dir=directory)
    except OSError as exc:
        raise Fatal(f"cannot write output {destination}: {exc}", EXIT_IO)
    stream = os.fdopen(fd, "w", encoding="utf-8", newline="")
    try:
        yield stream
        stream.flush()
        stream.close()
        os.replace(tmp, destination)
    except BaseException:
        try:
            stream.close()
        except Exception:
            pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Partitioned output
# --------------------------------------------------------------------------

SAFE_SEGMENT = frozenset(string.ascii_letters + string.digits + "._-")
NULL_SEGMENT = "_null"
MAX_OPEN_PARTS = 48


def encode_segment(text):
    """Percent-encode UTF-8 bytes outside [A-Za-z0-9._-], upper-case hex (T47)."""
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if char in SAFE_SEGMENT:
            out.append(char)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def partition_directory(root, columns, fragments):
    """`<col1>=<val1>/<col2>=<val2>/...` under `root`, values already cast.

    `columns` are the `--partition-by` paths exactly as the user wrote them
    (T78); `fragments` are this row's resolved values for those paths.
    """
    segments = []
    for name, value in zip(columns, fragments):
        # T54: every flavour of null collapses onto the one `_null` segment.
        text = NULL_SEGMENT if value is None else encode_segment(value)
        segments.append(f"{encode_segment(name)}={text}")
    return os.path.join(root, *segments)


class PartSink:
    """One partition directory's `part-xxxxx.csv` sequence."""

    def __init__(self, manager, directory):
        self.manager = manager
        self.directory = directory
        self.index = -1
        self.handle = None
        self.rows = 0
        self.size = 0

    def path(self):
        return os.path.join(self.directory, f"part-{self.index:05d}.csv")

    def write(self, line, size):
        manager = self.manager
        if self.index < 0:
            self._start()
        else:
            # T53: only cut a file that already holds at least one data row, so
            # an oversized row still lands in a (header-bearing) file of its own.
            cut = False
            if manager.max_rows is not None and self.rows + 1 > manager.max_rows:
                cut = True
            if manager.max_bytes is not None and self.size + size > manager.max_bytes:
                cut = True
            if cut and self.rows > 0:
                manager.release(self)
                self._start()
            elif self.handle is None:
                self.handle = manager.acquire(self, self.path(), "a", None)
            else:
                manager.touch(self)
        self.handle.write(line)
        self.rows += 1
        self.size += size

    def _start(self):
        manager = self.manager
        if self.index < 0:
            try:
                os.makedirs(self.directory, exist_ok=True)
            except OSError as exc:
                raise Fatal(f"cannot create partition directory "
                            f"{self.directory}: {exc}", EXIT_IO)
        self.index += 1
        self.rows = 0
        self.size = manager.header_size
        self.handle = manager.acquire(self, self.path(), "w",
                                      manager.header_line)


class PartManager:
    """Routes the sorted stream into per-partition shard writers.

    Only a bounded number of files stay open; evicted sinks are reopened in
    append mode, which keeps memory flat no matter how many partitions exist.
    """

    def __init__(self, root, header_line, max_rows, max_bytes):
        self.root = root
        self.header_line = header_line
        self.header_size = len(header_line.encode("utf-8"))
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.sinks = {}
        self.open = collections.OrderedDict()

    def sink(self, directory):
        found = self.sinks.get(directory)
        if found is None:
            found = self.sinks[directory] = PartSink(self, directory)
        return found

    def acquire(self, sink, path, mode, header):
        self._evict(MAX_OPEN_PARTS - 1)
        try:
            handle = open(path, mode, encoding="utf-8", newline="")
            if header is not None:
                handle.write(header)
        except OSError as exc:
            raise Fatal(f"cannot write output file {path}: {exc}", EXIT_IO)
        self.open[id(sink)] = sink
        return handle

    def touch(self, sink):
        self.open.move_to_end(id(sink))

    def release(self, sink):
        self.open.pop(id(sink), None)
        if sink.handle is not None:
            sink.handle.close()
            sink.handle = None

    def _evict(self, limit):
        while len(self.open) > limit:
            _, victim = self.open.popitem(last=False)
            if victim.handle is not None:
                victim.handle.close()
                victim.handle = None

    def close_all(self):
        self._evict(0)
        for sink in self.sinks.values():
            if sink.handle is not None:
                sink.handle.close()
                sink.handle = None


@contextlib.contextmanager
def open_output_dir(destination):
    """Build the tree in a sibling temp directory, then swap it in (T48, T57)."""
    dest = os.path.abspath(destination)
    parent = os.path.dirname(dest) or "."
    try:
        os.makedirs(parent, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".merge_files-", suffix=".tmp", dir=parent)
    except OSError as exc:
        raise Fatal(f"cannot write output {destination}: {exc}", EXIT_IO)

    stash = None
    moved = False
    try:
        yield tmp
        if os.path.lexists(dest):
            if not os.path.isdir(dest) or os.path.islink(dest):
                raise Fatal(f"cannot write output {destination}: "
                            f"exists and is not a directory", EXIT_IO)
            stash = tempfile.mkdtemp(prefix=".merge_files-old-", dir=parent)
            os.rename(dest, os.path.join(stash, "prev"))
            moved = True
        os.rename(tmp, dest)
        moved = False
    except Fatal:
        _undo_output_dir(tmp, stash, dest, moved)
        raise
    except OSError as exc:
        _undo_output_dir(tmp, stash, dest, moved)
        raise Fatal(f"cannot write output {destination}: {exc}", EXIT_IO)
    except BaseException:
        _undo_output_dir(tmp, stash, dest, moved)
        raise
    finally:
        if stash is not None:
            shutil.rmtree(stash, ignore_errors=True)


def _undo_output_dir(tmp, stash, dest, moved):
    """Drop the partial tree; put any displaced destination back."""
    shutil.rmtree(tmp, ignore_errors=True)
    if moved and not os.path.lexists(dest):
        try:
            os.rename(os.path.join(stash, "prev"), dest)
        except OSError:
            pass


def write_partitioned(args, names, rows, root, render_line):
    """Emit `part-xxxxx.csv` shards, optionally nested in Hive directories."""
    manager = PartManager(root, render_line(names),
                          args.max_rows_per_file, args.max_bytes_per_file)
    null_literal = args.null_literal
    try:
        for rec in rows:
            cells = rec[2]
            if args.partition:
                directory = partition_directory(root, args.partition, rec[3])
            else:
                directory = root
            line = render_line([null_literal if c is None else c for c in cells])
            manager.sink(directory).write(line, len(line.encode("utf-8")))
    finally:
        manager.close_all()


def make_writer(args, stream):
    return csv.writer(
        stream,
        delimiter=",",
        quotechar=args.quotechar,
        doublequote=True,
        escapechar=None,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )


def make_line_renderer(args):
    """Render one CSV record to exactly the text that would land on disk."""
    buffer = io.StringIO()
    writer = make_writer(args, buffer)

    def render_line(cells):
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow(cells)
        return buffer.getvalue()

    return render_line


def write_output(args, names, records, store, sort_key):
    if store.paths:
        store.reduce_runs(sort_key)
    else:
        records.sort(key=sort_key)
    handles = []
    try:
        if store.paths:
            runs = []
            for path in store.paths:
                handle = open(path, "r", encoding="utf-8")
                handles.append(handle)
                runs.append(_json_lines(handle))
            rows = heapq.merge(*runs, key=sort_key)
        else:
            rows = records

        if args.partitioned:
            render_line = make_line_renderer(args)
            with open_output_dir(args.output) as root:
                write_partitioned(args, names, rows, root, render_line)
            return

        with open_output(args.output) as stream:
            writer = make_writer(args, stream)
            writer.writerow(names)
            null_literal = args.null_literal
            for rec in rows:
                cells = rec[2]
                writer.writerow([null_literal if c is None else c for c in cells])
    except Fatal:
        raise
    except OSError as exc:
        raise Fatal(f"cannot write output: {exc}", EXIT_IO)
    finally:
        for handle in handles:
            handle.close()


def run(argv=None):
    args = parse_args(argv)
    dialect = Dialect(args.quotechar, args.escapechar)
    aliases = load_alias_table(args.type_alias_file)

    store = SpillStore(args.temp_dir)
    try:
        sources = build_sources(args, dialect, store)
        # Nested input is accepted only when a schema declares it (error 6).
        for source in sources:
            source.allow_nested = args.schema is not None

        if args.schema is not None:
            names, types = load_schema_document(args.schema, aliases)
        else:
            names, types = infer_schema(sources, args)

        missing = [k for k in args.keys if path_root(k, names) is None]
        if missing:
            raise Fatal(
                "key column(s) not present in resolved schema: "
                + ", ".join(missing), EXIT_SCHEMA
            )

        # T52: partition columns name resolved-schema columns, just like --key.
        unknown = [c for c in args.partition
                   if path_root(c, names, "partition") is None]
        if unknown:
            raise Fatal(
                "partition column(s) not present in resolved schema: "
                + ", ".join(unknown), EXIT_SCHEMA
            )

        keys = [compile_field_path(k, names, types, "key") for k in args.keys]
        partitions = [compile_field_path(c, names, types, "partition")
                      for c in args.partition]

        caster = Caster(names, types, args.on_type_error)
        records, sort_key = ingest(args, names, caster, store, sources,
                                   keys, partitions)
        write_output(args, names, records, store, sort_key)
    finally:
        store.cleanup()
    return 0


def main(argv=None):
    try:
        return run(argv)
    except Fatal as exc:
        sys.stderr.write(f"{PROG}: error: {exc}\n")
        return exc.code
    except BrokenPipeError:  # pragma: no cover - downstream closed stdout
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_IO
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    sys.exit(main())

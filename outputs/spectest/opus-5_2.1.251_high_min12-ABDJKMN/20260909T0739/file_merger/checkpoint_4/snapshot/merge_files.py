#!/usr/bin/env python3
"""Merge heterogeneous tabular inputs into a single schema-aligned, sorted CSV.

Supported inputs: CSV, TSV, JSON Lines (NDJSON) and Parquet, optionally gzipped.
Output is either a single CSV (file or stdout) or, when a partitioning flag is
given, a directory tree of Hive-style partitions and `part-xxxxx.csv` shards.
See AMBIGUITIES.md for the interpretation chosen wherever the spec left room.
"""

from __future__ import annotations

import argparse
import atexit
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
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from decimal import Decimal

PROG = "merge_files.py"

# --- exit codes (AMBIGUITIES T24) -----------------------------------------
EXIT_OK = 0
EXIT_ERROR = 1        # unclassified operational failure
EXIT_USAGE = 2        # bad invocation, unusable input path, undetectable format
EXIT_SCHEMA = 3       # schema problems, incl. a key column outside the schema
EXIT_CAST = 4         # cast failure under --on-type-error fail
EXIT_INPUT = 5        # malformed or misdeclared input (compression, dialect)
EXIT_NESTED = 6       # nested structure in JSONL/Parquet

STRING, INT, FLOAT, BOOL, DATE, TIMESTAMP = (
    "string", "int", "float", "bool", "date", "timestamp",
)
VALID_TYPES = (STRING, INT, FLOAT, BOOL, DATE, TIMESTAMP)
# Spec: "Type priority: timestamp > date > bool > int > float > string"
TYPE_PRIORITY = (TIMESTAMP, DATE, BOOL, INT, FLOAT, STRING)

FORMAT_CSV, FORMAT_TSV, FORMAT_JSONL, FORMAT_PARQUET = (
    "csv", "tsv", "jsonl", "parquet",
)
INPUT_FORMATS = (FORMAT_CSV, FORMAT_TSV, FORMAT_JSONL, FORMAT_PARQUET)
TEXT_FORMATS = (FORMAT_CSV, FORMAT_TSV)
# "prefer typed sources in precedence order" (AMBIGUITIES T28)
SOURCE_RANK = {
    FORMAT_CSV: 0, FORMAT_TSV: 0, FORMAT_JSONL: 1, FORMAT_PARQUET: 2,
}

EXTENSIONS = {
    ".csv": FORMAT_CSV,
    ".tsv": FORMAT_TSV,
    ".jsonl": FORMAT_JSONL,
    ".ndjson": FORMAT_JSONL,
    ".parquet": FORMAT_PARQUET,
}

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

DEFAULT_MEMORY_LIMIT_MB = 64
DEFAULT_ROW_GROUP_BYTES = 8 * 1024 * 1024
MAX_PARQUET_BATCH_ROWS = 8192
MAX_MERGE_FANIN = 32
MAX_OPEN_PARTS = 32          # simultaneously open part files (T50 fan-out cap)

# --- partitioned output (AMBIGUITIES T44-T47) ------------------------------
PART_TEMPLATE = "part-%05d.csv"
PART_SAFE = frozenset(string.ascii_letters + string.digits + "._-")
NULL_SEGMENT = "_null"

INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1

# Rank component of a sort key: nulls first, then well-typed values, then any
# raw text retained by --on-type-error keep-string.
RANK_NULL, RANK_VALUE, RANK_TEXT = 0, 1, 2

NULL, OK, ERR = "null", "ok", "err"

MISSING = object()   # the record simply has no such field

# The exact wording the spec gives for error 6.
NESTED_MESSAGE = "nested structure requires provided --schema"


class ToolError(Exception):
    """An operational error: reported on stderr, exits with `code`."""

    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


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
        return value if isinstance(value, str) else format_natural(value)
    if type_name == INT:
        return str(value)
    if type_name == FLOAT:
        return str(value)
    if type_name == BOOL:
        return "true" if value else "false"
    if type_name == DATE:
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    return format_timestamp(value)


def natural_type(value):
    """The type a already-typed (JSONL/Parquet) value carries by itself."""
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        return INT
    if isinstance(value, float):
        return FLOAT
    if isinstance(value, datetime):
        return TIMESTAMP
    if isinstance(value, date_cls):
        return DATE
    return STRING


def format_natural(value):
    return format_value(value, natural_type(value))


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
# Casting already-typed values (AMBIGUITIES T33)
# --------------------------------------------------------------------------

def finite(value):
    return value == value and value not in (float("inf"), float("-inf"))


def cast_typed(value, type_name):
    """Cast a JSONL/Parquet value to `type_name`; None means cast failure."""
    if type_name == STRING:
        if isinstance(value, float) and not finite(value):
            return str(value)
        return format_natural(value)

    if isinstance(value, bool):
        return value if type_name == BOOL else None

    if isinstance(value, int):
        if type_name == INT:
            return value
        if type_name == FLOAT:
            return float(value)
        if type_name == BOOL:
            # The text caster accepts `1`/`0`, so the typed one does too.
            if value in (0, 1):
                return bool(value)
        return None

    if isinstance(value, float):
        if not finite(value):
            return None
        if type_name == FLOAT:
            return value
        if type_name == INT:
            return int(value) if value.is_integer() else None
        return None

    if isinstance(value, datetime):
        return value if type_name == TIMESTAMP else None

    if isinstance(value, date_cls):
        if type_name == DATE:
            return value
        if type_name == TIMESTAMP:
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return None

    return None


def normalize_number(value):
    """JSON numbers: "prefer int if integer and within range" (T32)."""
    if isinstance(value, int):
        return value if INT64_MIN <= value <= INT64_MAX else float(value)
    if not finite(value):
        return value
    if value.is_integer():
        whole = int(value)
        if INT64_MIN <= whole <= INT64_MAX:
            return whole
    return value


def normalize_json_value(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return normalize_number(value)
    return str(value)


def normalize_typed_value(value):
    """Fold a Parquet cell into the small set of types the caster knows."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date_cls):
        return value
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            whole = int(value)
            if INT64_MIN <= whole <= INT64_MAX:
                return whole
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, time_cls):
        return value.isoformat()
    return str(value)


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------

STRING_ONLY = frozenset((STRING,))
BOOL_CANDIDATES = frozenset((BOOL, STRING))
INT_CANDIDATES = frozenset((INT, FLOAT, STRING))
FLOAT_CANDIDATES = frozenset((FLOAT, STRING))
TIMESTAMP_CANDIDATES = frozenset((TIMESTAMP, STRING))
DATE_CANDIDATES = frozenset((DATE, STRING))


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


def typed_candidates(value):
    if isinstance(value, bool):
        return BOOL_CANDIDATES
    if isinstance(value, int):
        return INT_CANDIDATES
    if isinstance(value, float):
        return FLOAT_CANDIDATES if finite(value) else STRING_ONLY
    if isinstance(value, datetime):
        return TIMESTAMP_CANDIDATES
    if isinstance(value, date_cls):
        return DATE_CANDIDATES
    return STRING_ONLY


def observe_candidates(value, typed, mode, is_null):
    """Candidate types contributed by one cell; None = not an observation."""
    if value is MISSING or value is None:
        return None
    if isinstance(value, str):
        if is_null(value):
            if typed:
                return None  # a typed null is missing, never an observation
            # loose: "empty strings ... don't affect inference" (T1).
            return None if mode == "loose" else STRING_ONLY
        # "JSONL values come typed (string/number/bool/null)": a typed source
        # states the type, so its strings stay strings (T40).  Text sources
        # have their type inferred from the lexeme.
        return STRING_ONLY if typed else candidate_types(value)
    if not typed:
        return candidate_types(str(value))
    return typed_candidates(value)


def best_type(candidates):
    for type_name in TYPE_PRIORITY:
        if type_name in candidates:
            return type_name
    return STRING


# --------------------------------------------------------------------------
# Nested types: the type model
# --------------------------------------------------------------------------

class JsonType:
    """`json` (and the bare `struct` alias): any JSON value, normalised only."""

    __slots__ = ()

    def __repr__(self):  # pragma: no cover - debugging aid
        return "json"


JSON = JsonType()


class StructType:
    """An ordered list of `(name, type)` fields; names unique within it."""

    __slots__ = ("fields", "index")

    def __init__(self, fields):
        self.fields = fields
        self.index = {name: node for name, node in fields}


class ArrayType:
    __slots__ = ("element",)

    def __init__(self, element):
        self.element = element


class MapType:
    """`map<string,T>`: string keys only, so only the value type is kept."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def is_primitive(node):
    return isinstance(node, str)


def type_label(node):
    """How a type is named in an error message."""
    if isinstance(node, str):
        return node
    if isinstance(node, JsonType):
        return "json"
    if isinstance(node, StructType):
        return "struct"
    if isinstance(node, ArrayType):
        return "array<%s>" % type_label(node.element)
    return "map<string,%s>" % type_label(node.value)


# --------------------------------------------------------------------------
# Type aliases
# --------------------------------------------------------------------------

# "Built-in aliases (always present)".  `list<T>` -> `array<T>` is expressed as
# a rewrite of the generic head, and `json` -> `struct` makes the bare `struct`
# name mean "any JSON value" (AMBIGUITIES T56).
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

MAX_TYPE_DEPTH = 64
INDEX_RE = re.compile(r"^\d+$")


def load_aliases(spec):
    """`--type-alias-file`: built-ins overlaid with the file's own aliases."""
    aliases = dict(BUILTIN_ALIASES)
    if spec is None:
        return aliases
    try:
        with open(spec, "r", encoding="utf-8-sig") as stream:
            document = json.load(stream)
    except OSError as exc:
        raise ToolError(
            f"cannot read type alias file {spec!r}: {exc.strerror or exc}", EXIT_USAGE
        )
    except ValueError as exc:
        raise ToolError(f"invalid JSON in type alias file {spec!r}: {exc}", EXIT_USAGE)

    if not isinstance(document, dict):
        raise ToolError(
            f"type alias file {spec!r} must hold a JSON object", EXIT_USAGE
        )
    table = document.get("aliases", document)
    if not isinstance(table, dict):
        raise ToolError(
            f"type alias file {spec!r} must hold an 'aliases' object", EXIT_USAGE
        )
    for name, target in table.items():
        if not isinstance(name, str) or not name.strip():
            raise ToolError(
                f"type alias file {spec!r}: alias names must be non-empty strings",
                EXIT_USAGE,
            )
        if not isinstance(target, str) or not target.strip():
            raise ToolError(
                f"type alias file {spec!r}: alias {name!r} must name a type",
                EXIT_USAGE,
            )
        # "Aliases apply after lowercasing names".
        aliases[name.strip().lower()] = target.strip().lower()
    check_alias_cycles(aliases)
    return aliases


def check_alias_cycles(aliases):
    """Resolve every alias eagerly so a cycle errors even when unused (T55)."""
    for start in aliases:
        seen = {start}
        name = aliases[start]
        while name in aliases:
            if name in seen:
                raise ToolError(
                    f"type alias cycle involving {start!r}", EXIT_USAGE
                )
            seen.add(name)
            name = aliases[name]


def resolve_alias_name(name, aliases):
    """Follow an alias chain transitively; cycles are error 2."""
    seen = {name}
    while name in aliases:
        name = aliases[name]
        if name in seen:
            raise ToolError(f"type alias cycle involving {name!r}", EXIT_USAGE)
        seen.add(name)
    return name


def split_generic(text):
    """`map<string,array<int>>` -> ('map', ['string', 'array<int>'])."""
    start = text.index("<")
    head = text[:start].strip()
    if not text.endswith(">"):
        return None, None
    body = text[start + 1:-1]
    args, depth, current = [], 0, []
    for char in body:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth < 0:
                return None, None
        if char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if depth != 0:
        return None, None
    args.append("".join(current).strip())
    return head, args


def parse_type(node, aliases, where, depth=0):
    """Turn a schema `type` value into a primitive name or a nested type."""
    if depth > MAX_TYPE_DEPTH:
        raise ToolError(
            f"type alias resolution does not terminate for {where}", EXIT_USAGE
        )
    if isinstance(node, str):
        return parse_type_string(node, aliases, where, depth)
    if isinstance(node, dict):
        kinds = {}
        for key, value in node.items():
            if isinstance(key, str):
                kinds[key.strip().lower()] = value
        if len(kinds) == 1:
            kind, body = next(iter(kinds.items()))
            kind = resolve_alias_name(kind, aliases)
            if kind == "struct":
                return parse_struct(body, aliases, where, depth)
            if kind == "array":
                return ArrayType(
                    parse_type(array_element(body, where), aliases, where, depth + 1)
                )
            if kind == "map":
                return parse_map(body, aliases, where, depth)
    raise ToolError(invalid_type_message(node, where), EXIT_SCHEMA)


def invalid_type_message(node, where):
    shown = node if isinstance(node, str) else json.dumps(node, sort_keys=True)
    return (
        f"invalid type {shown!r} for {where}; valid types are: "
        f"{', '.join(VALID_TYPES)}, struct, array<T>, map<string,T>, json"
    )


def parse_struct(body, aliases, where, depth):
    fields = body.get("fields") if isinstance(body, dict) else body
    if not isinstance(fields, list):
        raise ToolError(
            f"struct type for {where} requires a 'fields' list", EXIT_SCHEMA
        )
    out, seen = [], set()
    for entry in fields:
        if not isinstance(entry, dict):
            raise ToolError(
                f"each struct field of {where} must be a JSON object", EXIT_SCHEMA
            )
        name = entry.get("name")
        if not isinstance(name, str) or name == "":
            raise ToolError(
                f"each struct field of {where} requires a non-empty 'name'",
                EXIT_SCHEMA,
            )
        if name in seen:
            raise ToolError(
                f"duplicate struct field {name!r} in {where}", EXIT_SCHEMA
            )
        seen.add(name)
        out.append((name, parse_type(entry.get("type", STRING), aliases,
                                     f"{where}.{name}", depth + 1)))
    return StructType(out)


def array_element(body, where):
    if isinstance(body, dict):
        if "element" in body:
            return body["element"]
        if body:
            return body       # `{"array": {"struct": {...}}}`
    elif isinstance(body, (str, list)):
        return body
    raise ToolError(
        f"array type for {where} requires an 'element' type", EXIT_SCHEMA
    )


def parse_map(body, aliases, where, depth):
    if not isinstance(body, dict) or "value" not in body:
        raise ToolError(
            f"map type for {where} requires a 'value' type", EXIT_SCHEMA
        )
    key_type = parse_type(body.get("key", STRING), aliases, where, depth + 1)
    if key_type != STRING:
        raise ToolError(
            f"map type for {where} must have string keys, not "
            f"{type_label(key_type)}",
            EXIT_SCHEMA,
        )
    return MapType(parse_type(body["value"], aliases, where, depth + 1))


def parse_type_string(text, aliases, where, depth):
    name = text.strip().lower()
    seen = {name}
    while name in aliases:
        name = aliases[name].strip().lower()
        if name in seen:
            raise ToolError(f"type alias cycle involving {text!r}", EXIT_USAGE)
        seen.add(name)
    if "<" in name:
        head, args = split_generic(name)
        if head is None:
            raise ToolError(invalid_type_message(text, where), EXIT_SCHEMA)
        head = resolve_alias_name(head, aliases)
        if head == "array" and len(args) == 1:
            return ArrayType(parse_type(args[0], aliases, where, depth + 1))
        if head == "map" and len(args) in (1, 2):
            if len(args) == 2:
                key_type = parse_type(args[0], aliases, where, depth + 1)
                if key_type != STRING:
                    raise ToolError(
                        f"map type for {where} must have string keys, not "
                        f"{type_label(key_type)}",
                        EXIT_SCHEMA,
                    )
            return MapType(parse_type(args[-1], aliases, where, depth + 1))
        raise ToolError(invalid_type_message(text, where), EXIT_SCHEMA)
    if name in VALID_TYPES:
        return name
    if name == "struct":
        return JSON        # `json` resolves here (AMBIGUITIES T56)
    raise ToolError(invalid_type_message(text, where), EXIT_SCHEMA)


# --------------------------------------------------------------------------
# Canonical JSON output
# --------------------------------------------------------------------------

class Kept(str):
    """A leaf retained verbatim by `--on-type-error keep-string`."""

    __slots__ = ()


def json_string(text):
    # RFC 8259 escaping; non-ASCII stays UTF-8 (AMBIGUITIES T58).
    return json.dumps(str(text), ensure_ascii=False)


def json_float(value):
    if not finite(value):
        return "null"
    return repr(value)


def json_text(node):
    parts = []
    emit_json(node, parts)
    return "".join(parts)


def emit_json(node, out):
    if node is None:
        out.append("null")
    elif node is True:
        out.append("true")
    elif node is False:
        out.append("false")
    elif isinstance(node, str):
        out.append(json_string(node))
    elif isinstance(node, int):
        out.append(str(node))
    elif isinstance(node, float):
        out.append(json_float(node))
    elif isinstance(node, datetime):
        out.append(json_string(format_timestamp(node)))
    elif isinstance(node, date_cls):
        out.append(json_string(format_value(node, DATE)))
    elif isinstance(node, dict):
        out.append("{")
        first = True
        for key, value in node.items():
            if not first:
                out.append(",")
            first = False
            out.append(json_string(key))
            out.append(":")
            emit_json(value, out)
        out.append("}")
    elif isinstance(node, (list, tuple)):
        out.append("[")
        for index, value in enumerate(node):
            if index:
                out.append(",")
            emit_json(value, out)
        out.append("]")
    else:
        out.append(json_string(format_natural(node)))


# --------------------------------------------------------------------------
# Recursive casting into nested types
# --------------------------------------------------------------------------

class Caster:
    """Casts values into declared types, applying `--on-type-error`."""

    def __init__(self, is_null, on_type_error):
        self.is_null = is_null
        self.mode = on_type_error
        self.file = ""
        self.line = 0

    def at(self, path, line):
        self.file = path
        self.line = line

    def failed(self, text, type_node, path):
        if self.mode == "coerce-null":
            return None
        if self.mode == "keep-string":
            return Kept(text)
        raise ToolError(
            f'cannot cast "{text}" to {type_label(type_node)} in field '
            f'"{".".join(path)}" (file={self.file} line={self.line})',
            EXIT_CAST,
        )

    def cast(self, value, type_node, path):
        """Cast one (possibly nested) value; returns a JSON-shaped node."""
        if value is MISSING or value is None:
            return None
        if isinstance(type_node, JsonType):
            return normalize_free_json(value)
        if is_primitive(type_node):
            if isinstance(value, (dict, list)):
                # "schema declares flat type but input has object/array"
                return self.failed(json_text(normalize_free_json(value)),
                                   type_node, path)
            status, casted, text = cast_cell(value, type_node, True, self.is_null)
            if status == NULL:
                return None
            if status == OK:
                return casted
            return self.failed(text, type_node, path)
        if isinstance(type_node, StructType):
            if not isinstance(value, dict):
                return self.failed(self.stringify(value), type_node, path)
            out = {}
            for name, field_type in type_node.fields:
                path.append(name)
                out[name] = self.cast(value.get(name, MISSING), field_type, path)
                path.pop()
            return out
        if isinstance(type_node, ArrayType):
            if not isinstance(value, list):
                return self.failed(self.stringify(value), type_node, path)
            out = []
            for index, item in enumerate(value):
                path.append(str(index))
                out.append(self.cast(item, type_node.element, path))
                path.pop()
            return out
        if not isinstance(value, dict):
            return self.failed(self.stringify(value), type_node, path)
        out = {}
        # "Map keys sorted lexicographically"
        for key in sorted(str(k) for k in value):
            path.append(key)
            out[key] = self.cast(value[key], type_node.value, path)
            path.pop()
        return out

    @staticmethod
    def stringify(value):
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json_text(normalize_free_json(value))
        return format_natural(normalize_typed_value(value))


def normalize_free_json(value):
    """`json` columns: accept any JSON value, normalise only (T57)."""
    if isinstance(value, dict):
        return {
            str(key): normalize_free_json(value[key])
            for key in sorted(str(k) for k in value)
        }
    if isinstance(value, (list, tuple)):
        return [normalize_free_json(item) for item in value]
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return normalize_number(value)
    return normalize_typed_value(value)


# --------------------------------------------------------------------------
# Field paths (`user.id`, `items.0.sku`, `attrs["country"]`)
# --------------------------------------------------------------------------

class FieldPath:
    """A parsed `--key` / `--partition-by` argument."""

    __slots__ = ("text", "segments", "slot", "leaf", "column")

    def __init__(self, text, segments):
        self.text = text
        self.segments = segments
        self.slot = None
        self.leaf = None      # declared primitive type, None when dynamic
        self.column = segments[0] if segments else text


def split_field_paths(value):
    """Split on commas that are outside `[...]` brackets."""
    parts, current, depth, quote = [], [], 0, None
    for char in value:
        if quote is not None:
            current.append(char)
            if char == quote and (len(current) < 2 or current[-2] != "\\"):
                quote = None
            continue
        if char in "\"'" and depth:
            quote = char
            current.append(char)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def parse_field_path(text, flag):
    """`a.b["c"].0` -> ['a', 'b', 'c', '0'] (bracket quoting removed)."""
    body = text.strip()
    if not body:
        raise ToolError(f"{flag} must name at least one non-empty column",
                        EXIT_USAGE)

    def malformed():
        return ToolError(f"{flag}: malformed field path {text!r}", EXIT_USAGE)

    segments, current, index, bracketed = [], [], 0, False
    while index < len(body):
        char = body[index]
        if char == ".":
            if current:
                segments.append("".join(current))
                current = []
            elif not bracketed:
                raise malformed()      # empty segment, e.g. `a..b` or `.a`
            bracketed = False
            index += 1
        elif char == "[":
            close = find_bracket_end(body, index)
            if close is None:
                raise malformed()
            if current:
                segments.append("".join(current))
                current = []
            elif not segments:
                raise malformed()      # a path cannot start with a bracket
            segments.append(unquote_bracket(body[index + 1:close], text, flag))
            bracketed = True
            index = close + 1
        else:
            if bracketed:
                raise malformed()      # `a["b"]c`
            current.append(char)
            index += 1
    if current:
        segments.append("".join(current))
    elif not bracketed:
        raise malformed()              # a trailing `.`
    if not segments or not segments[0]:
        raise malformed()
    return FieldPath(text, segments)


def find_bracket_end(text, start):
    index, quote = start + 1, None
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "]":
            return index
        index += 1
    return None


def unquote_bracket(body, text, flag):
    body = body.strip()
    if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
        inner, out, index = body[1:-1], [], 0
        while index < len(inner):
            if inner[index] == "\\" and index + 1 < len(inner):
                out.append(inner[index + 1])
                index += 2
            else:
                out.append(inner[index])
                index += 1
        return "".join(out)
    if body == "":
        raise ToolError(f"{flag}: malformed field path {text!r}", EXIT_USAGE)
    return body


def resolve_path_type(column_type, path, what):
    """Static walk of a field path; returns the leaf type, or None if dynamic."""
    node = column_type
    for segment in path.segments[1:]:
        if isinstance(node, JsonType):
            return None                      # checked per row instead (T63)
        if is_primitive(node):
            raise not_primitive(path, what)
        if isinstance(node, StructType):
            if segment not in node.index:
                raise not_primitive(path, what)
            node = node.index[segment]
        elif isinstance(node, ArrayType):
            if not INDEX_RE.match(segment):
                # "Array indices must be non-negative integers"
                raise not_primitive(path, what)
            node = node.element
        else:
            node = node.value
    if is_primitive(node):
        return node
    raise not_primitive(path, what)


def not_primitive(path, what):
    return ToolError(
        f'{what} column "{path.text}" does not resolve to a primitive', EXIT_SCHEMA
    )


def lookup_path(node, segments):
    """Read a field path out of one casted column value."""
    for segment in segments:
        if node is None:
            return None
        if isinstance(node, dict):
            node = node.get(segment)
        elif isinstance(node, list):
            if not INDEX_RE.match(segment):
                return None
            index = int(segment)
            node = node[index] if index < len(node) else None
        else:
            return None
    return node


DYNAMIC_ORDER = {BOOL: 0, INT: 1, FLOAT: 1, STRING: 2, DATE: 3, TIMESTAMP: 4}


def path_fragment(value, leaf_type, path, what):
    """The sort-key fragment contributed by one path."""
    if value is None:
        return [RANK_NULL, 0]
    if isinstance(value, Kept):
        return [RANK_TEXT, str(value)]
    if leaf_type is None:
        if isinstance(value, (dict, list)):
            raise not_primitive(path, what)
        natural = natural_type(value)
        return [RANK_VALUE, [DYNAMIC_ORDER[natural], sort_value(value, natural)]]
    return [RANK_VALUE, sort_value(value, leaf_type)]


def path_text_value(value, leaf_type, path, what):
    """The rendered text of a path value, or None when the value is null."""
    if value is None:
        return None
    if isinstance(value, Kept):
        return str(value)
    if leaf_type is None:
        if isinstance(value, (dict, list)):
            raise not_primitive(path, what)
        return format_natural(value)
    return format_value(value, leaf_type)


# --------------------------------------------------------------------------
# Input dialects, decompression and format detection
# --------------------------------------------------------------------------

class Dialect:
    """The CSV dialect used for reading CSV inputs and writing the output."""

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

    def writer(self, stream):
        return csv.writer(
            stream,
            delimiter=",",
            quotechar=self.quotechar,
            escapechar=self.escapechar,
            doublequote=self.escapechar is None,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )


@contextmanager
def read_errors(path, kind):
    """Map low-level read failures onto the spec's error classes."""
    try:
        yield
    except ToolError:
        raise
    except (gzip.BadGzipFile, zlib.error, EOFError) as exc:
        raise ToolError(f"{path}: gzip decompression failed: {exc}", EXIT_INPUT)
    except UnicodeDecodeError as exc:
        raise ToolError(f"{path}: input is not valid UTF-8: {exc}", EXIT_INPUT)
    except csv.Error as exc:
        raise ToolError(f"{path}: malformed {kind}: {exc}", EXIT_INPUT)
    except OSError as exc:
        raise ToolError(
            f"cannot read input {path!r}: {exc.strerror or exc}", EXIT_ERROR
        )


def peek_bytes(path, count=8):
    try:
        with open(path, "rb") as handle:
            return handle.read(count)
    except OSError as exc:
        raise ToolError(
            f"cannot read input {path!r}: {exc.strerror or exc}", EXIT_USAGE
        )


def resolve_compression(path, flag):
    """`--compression`: extension or flag, cross-checked against magic bytes."""
    head = peek_bytes(path, 2)
    actual = "gzip" if head[:2] == GZIP_MAGIC else "none"
    if flag == "auto":
        resolved = "gzip" if path.lower().endswith(".gz") else "none"
    else:
        resolved = flag
    if head and resolved != actual:
        raise ToolError(
            f"{path}: compression mismatch: expected {resolved} data but the "
            f"file looks like {actual}",
            EXIT_INPUT,
        )
    return resolved


def strip_gzip_suffix(name):
    return name[:-3] if name.endswith(".gz") else name


def sniff_head(path, compression, count=4):
    """First bytes of the *decompressed* stream."""
    with read_errors(path, "input"):
        with open(path, "rb") as handle:
            if compression == "gzip":
                with gzip.GzipFile(fileobj=handle, mode="rb") as stream:
                    return stream.read(count)
            return handle.read(count)


def resolve_format(path, flag, compression):
    """`--input-format`: explicit wins, else extension, else magic bytes."""
    if flag != "auto":
        return flag
    name = strip_gzip_suffix(os.path.basename(path).lower())
    extension = os.path.splitext(name)[1]
    known = EXTENSIONS.get(extension)
    if known is not None:
        return known
    if sniff_head(path, compression, 4) == PARQUET_MAGIC:
        return FORMAT_PARQUET
    raise ToolError(
        f"{path}: cannot determine input format from the file name or its "
        f"contents; pass --input-format",
        EXIT_USAGE,
    )


def import_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ToolError(f"reading Parquet requires pyarrow: {exc}", EXIT_ERROR)
    return pa, pq


def arrow_value_width(pa, arrow_type):
    """Rough per-value byte estimate, used only for batch sizing."""
    if pa.types.is_boolean(arrow_type):
        return 1
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return 32
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return 32
    try:
        return max(1, arrow_type.bit_width // 8)
    except (ValueError, AttributeError):
        return 16


def arrow_value(pa, value, arrow_type):
    """Convert one Arrow value into plain JSON shapes (maps become objects)."""
    if value is None:
        return None
    if pa.types.is_map(arrow_type):
        item_type = arrow_type.item_type
        out = {}
        for pair in value:
            if isinstance(pair, dict):
                key, item = pair.get("key"), pair.get("value")
            else:
                key, item = pair
            out[str(key)] = arrow_value(pa, item, item_type)
        return out
    if pa.types.is_struct(arrow_type):
        if not isinstance(value, dict):
            return normalize_typed_value(value)
        return {
            field.name: arrow_value(pa, value.get(field.name), field.type)
            for field in arrow_type
        }
    if (pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type)
            or pa.types.is_fixed_size_list(arrow_type)):
        item_type = arrow_type.value_type
        return [arrow_value(pa, item, item_type) for item in value]
    return normalize_typed_value(value)


# --------------------------------------------------------------------------
# Input sources
# --------------------------------------------------------------------------

class Options:
    """Everything the readers need that comes from the command line."""

    def __init__(self, dialect, is_null, row_group_bytes, memory_budget):
        self.dialect = dialect
        self.is_null = is_null
        self.row_group_bytes = row_group_bytes
        self.memory_budget = memory_budget


class Source:
    """One input file, with its resolved format and compression."""

    def __init__(self, path, fmt, compression, options):
        self.path = path
        self.format = fmt
        self.compression = compression
        self.options = options
        self.typed = fmt in (FORMAT_JSONL, FORMAT_PARQUET)
        self.rank = SOURCE_RANK[fmt]
        # Declared column types, or None while no --schema is in play; nested
        # input is only allowed once a schema exists.
        self.schema = None

    # -- plumbing ---------------------------------------------------------
    def _open_binary(self):
        try:
            handle = open(self.path, "rb")
        except OSError as exc:
            raise ToolError(
                f"cannot read input {self.path!r}: {exc.strerror or exc}",
                EXIT_USAGE,
            )
        if self.compression != "gzip":
            return handle
        try:
            return gzip.GzipFile(fileobj=handle, mode="rb")
        except OSError as exc:
            handle.close()
            raise ToolError(
                f"{self.path}: gzip decompression failed: {exc}", EXIT_INPUT
            )

    # -- discovery --------------------------------------------------------
    def field_names(self):
        """Declared field names, or None when only the data knows (JSONL)."""
        if self.format in TEXT_FORMATS:
            return self._text_header()[0]
        if self.format == FORMAT_PARQUET:
            return self._parquet_names()
        return None

    def _text_header(self):
        with ExitStack() as stack:
            reader, _stream = self._text_reader(stack)
            with read_errors(self.path, self.format.upper()):
                header = next(reader, None)
        return self._unique_header(header or [])

    @staticmethod
    def _unique_header(header):
        """(names, positions) with the first occurrence of a name winning."""
        names, positions = [], {}
        for position, name in enumerate(header):
            if name not in positions:
                positions[name] = position
                names.append(name)
        return names, positions

    def _text_reader(self, stack):
        binary = stack.enter_context(self._open_binary())
        stream = stack.enter_context(
            io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        )
        if self.format == FORMAT_TSV:
            # "delimiter is tab, no quoting"
            reader = csv.reader(
                stream, delimiter="\t", quoting=csv.QUOTE_NONE,
                escapechar=None, doublequote=False,
            )
        else:
            reader = self.options.dialect.reader(stream)
        return reader, stream

    def _parquet_file(self, stack):
        pa, pq = import_pyarrow()
        with read_errors(self.path, "Parquet"):
            try:
                if self.compression == "gzip":
                    handle = stack.enter_context(self._open_binary())
                    parquet = pq.ParquetFile(handle)
                else:
                    parquet = pq.ParquetFile(self.path)
            except (pa.ArrowInvalid, pa.ArrowException) as exc:
                raise ToolError(f"{self.path}: malformed Parquet: {exc}", EXIT_INPUT)
        schema = parquet.schema_arrow
        self._check_flat(pa, schema)
        return pa, parquet, schema

    def _check_flat(self, pa, schema):
        if self.schema is not None:
            # "With --schema, Parquet/JSONL nesting must structurally match":
            # the check moves to the caster, per column and per value.
            return
        for field in schema:
            arrow_type = field.type
            nested = (
                pa.types.is_list(arrow_type)
                or pa.types.is_large_list(arrow_type)
                or pa.types.is_fixed_size_list(arrow_type)
                or pa.types.is_struct(arrow_type)
                or pa.types.is_map(arrow_type)
                or pa.types.is_union(arrow_type)
                or pa.types.is_nested(arrow_type)
            )
            if nested:
                raise ToolError(NESTED_MESSAGE, EXIT_NESTED)

    def _parquet_names(self):
        with ExitStack() as stack:
            _pa, _parquet, schema = self._parquet_file(stack)
            return list(schema.names)

    # -- record iteration -------------------------------------------------
    def iter_records(self):
        if self.format in TEXT_FORMATS:
            return self._iter_text()
        if self.format == FORMAT_JSONL:
            return self._iter_jsonl()
        return self._iter_parquet()

    def _iter_text(self):
        kind = self.format.upper()
        with ExitStack() as stack:
            reader, _stream = self._text_reader(stack)
            with read_errors(self.path, kind):
                header = next(reader, None)
                if not header:
                    return
                names, positions = self._unique_header(header)
                width = len(header)
                for row in reader:
                    if not row:
                        continue  # a stray blank line is not a record
                    if self.format == FORMAT_TSV and len(row) > width:
                        raise ToolError(
                            f"{self.path}:{reader.line_num}: row has "
                            f"{len(row)} fields but the header has {width}; "
                            f"literal tabs inside a field are not allowed",
                            EXIT_INPUT,
                        )
                    record = {
                        name: (row[position] if position < len(row) else "")
                        for name, position in positions.items()
                    }
                    yield (self.path, reader.line_num), record

    def _iter_jsonl(self):
        with ExitStack() as stack:
            binary = stack.enter_context(self._open_binary())
            stream = stack.enter_context(
                io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
            )
            with read_errors(self.path, "JSONL"):
                for line_no, line in enumerate(stream, 1):
                    text = line.strip()
                    if not text:
                        continue  # "blank/whitespace lines ignored"
                    try:
                        obj = json.loads(text)
                    except ValueError as exc:
                        raise ToolError(
                            f"{self.path}:{line_no}: malformed JSON: {exc}",
                            EXIT_INPUT,
                        )
                    if not isinstance(obj, dict):
                        raise ToolError(
                            f"{self.path}:{line_no}: line is not a JSON object",
                            EXIT_NESTED,
                        )
                    record = {}
                    for key, value in obj.items():
                        if isinstance(value, (list, dict)):
                            if self.schema is None:
                                raise ToolError(NESTED_MESSAGE, EXIT_NESTED)
                            # Structure is kept raw; the caster matches it
                            # against the declared type for this column.
                            record[key] = value
                        else:
                            record[key] = normalize_json_value(value)
                    yield (self.path, line_no), record

    def _batch_rows(self, pa, schema):
        estimate = sum(arrow_value_width(pa, field.type) for field in schema)
        estimate = max(estimate, 16)
        budget = min(self.options.row_group_bytes, self.options.memory_budget)
        rows = max(1, budget // estimate)
        return int(min(rows, MAX_PARQUET_BATCH_ROWS))

    def _iter_parquet(self):
        with ExitStack() as stack:
            pa, parquet, schema = self._parquet_file(stack)
            batch_rows = self._batch_rows(pa, schema)
            nested = {
                field.name: field.type
                for field in schema
                if pa.types.is_nested(field.type)
            }
            row_no = 0
            with read_errors(self.path, "Parquet"):
                # Streamed row group-wise: one batch is resident at a time.
                for batch in parquet.iter_batches(batch_size=batch_rows):
                    for record in batch.to_pylist():
                        row_no += 1
                        if nested:
                            row = {
                                key: (
                                    arrow_value(pa, value, nested[key])
                                    if key in nested
                                    else normalize_typed_value(value)
                                )
                                for key, value in record.items()
                            }
                        else:
                            row = {
                                key: normalize_typed_value(value)
                                for key, value in record.items()
                            }
                        yield (self.path, row_no), row

    # -- inference --------------------------------------------------------
    def observe(self, mode, is_null):
        """Candidate types per column, or None for a column with no values."""
        local = {}
        declared = self.field_names()
        if declared is not None:
            for name in declared:
                local[name] = None
        typed = self.typed
        for _locator, record in self.iter_records():
            for name, value in record.items():
                found = observe_candidates(value, typed, mode, is_null)
                if found is None:
                    if name not in local:
                        local[name] = None
                    continue
                current = local.get(name)
                local[name] = found if current is None else (current & found)
        return local


def build_sources(paths, input_format, compression, options):
    sources = []
    for path in paths:
        if not os.path.exists(path):
            raise ToolError(f"input file not found: {path}", EXIT_USAGE)
        if os.path.isdir(path):
            raise ToolError(f"input is a directory: {path}", EXIT_USAGE)
        resolved_compression = resolve_compression(path, compression)
        resolved_format = resolve_format(path, input_format, resolved_compression)
        sources.append(Source(path, resolved_format, resolved_compression, options))
    return sources


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------

class Column:
    __slots__ = ("name", "type")

    def __init__(self, name, type_name):
        self.name = name
        self.type = type_name


def load_schema(spec, aliases):
    """`--schema` names a JSON file; inline JSON is also accepted (T10)."""
    document = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as stream:
                document = json.load(stream)
        except OSError as exc:
            raise ToolError(
                f"cannot read schema {spec!r}: {exc.strerror or exc}", EXIT_SCHEMA
            )
        except ValueError as exc:
            raise ToolError(f"invalid schema JSON in {spec!r}: {exc}", EXIT_SCHEMA)
    else:
        stripped = spec.strip()
        if stripped.startswith("{"):
            try:
                document = json.loads(stripped)
            except ValueError as exc:
                raise ToolError(f"invalid schema JSON: {exc}", EXIT_SCHEMA)
        else:
            raise ToolError(f"schema file not found: {spec!r}", EXIT_SCHEMA)

    if not isinstance(document, dict) or not isinstance(document.get("columns"), list):
        raise ToolError(
            "schema must be a JSON object with a 'columns' list", EXIT_SCHEMA
        )

    columns = []
    seen = set()
    for entry in document["columns"]:
        if not isinstance(entry, dict):
            raise ToolError("each schema column must be a JSON object", EXIT_SCHEMA)
        name = entry.get("name")
        if not isinstance(name, str) or name == "":
            raise ToolError(
                "each schema column requires a non-empty 'name'", EXIT_SCHEMA
            )
        type_node = parse_type(entry.get("type", STRING), aliases,
                               f"column {name!r}")
        if name in seen:
            raise ToolError(f"duplicate column {name!r} in schema", EXIT_SCHEMA)
        seen.add(name)
        columns.append(Column(name, type_node))
    return columns


def combine_candidates(sets, mode):
    """Fold several per-file candidate sets into one type (T31)."""
    if not sets:
        return STRING
    if mode == "loose":
        pooled = None
        for candidates in sets:
            pooled = candidates if pooled is None else pooled & candidates
        return best_type(pooled)
    observed = {best_type(candidates) for candidates in sets}
    return observed.pop() if len(observed) == 1 else STRING


def resolve_type(observations, name, mode, strategy):
    """Pick the final type of `name` given every file's observations."""
    seen = [
        (rank, local[name])
        for rank, local in observations
        if local.get(name) is not None
    ]
    if not seen:
        return STRING  # the column exists but holds no values anywhere

    if strategy == "union":
        # "simplest common type that can hold all observed values" (T30)
        pooled = None
        for _rank, candidates in seen:
            pooled = candidates if pooled is None else pooled & candidates
        return best_type(pooled)

    if strategy == "consensus":
        # "type that majority of files support" (T29)
        votes = {}
        for _rank, candidates in seen:
            chosen = best_type(candidates)
            votes[chosen] = votes.get(chosen, 0) + 1
        top = max(votes.values())
        for type_name in TYPE_PRIORITY:
            if votes.get(type_name, 0) == top:
                return type_name
        return STRING

    # authoritative: "prefer typed sources in precedence order" (T28)
    top_rank = max(rank for rank, _candidates in seen)
    return combine_candidates(
        [candidates for rank, candidates in seen if rank == top_rank], mode
    )


def infer_schema(sources, mode, strategy, is_null):
    """Union of all input fields, lexicographically ordered, with types."""
    names = set()
    observations = []
    for source in sources:
        local = source.observe(mode, is_null)
        names.update(local)
        observations.append((source.rank, local))
    return [
        Column(name, resolve_type(observations, name, mode, strategy))
        for name in sorted(names)
    ]


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
            raise ToolError(
                f"cannot create temporary file: {exc.strerror or exc}", EXIT_ERROR
            )
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

    def add(self, key, seq, row, segments=None):
        record = [key, seq, row] if segments is None else [key, seq, row, segments]
        self.buffer.append(record)
        # Rough accounting: payload plus per-object interpreter overhead
        # (a buffered cell is a str object inside a list; a key cell is a
        # two-element list of its own).
        self.pending_bytes += 200 + sum(len(cell) + 90 for cell in row)
        self.pending_bytes += 150 * len(key)
        if segments is not None:
            self.pending_bytes += sum(len(segment) + 90 for segment in segments)
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

    def sorted_records(self, stack):
        """Yield records in final order. `stack` owns the run file handles."""
        if not self.store.paths:
            self.buffer.sort(key=self.record_key)
            for record in self.buffer:
                yield record
            self.buffer = []
            return
        self.spill()
        runs = self._fold_runs(list(self.store.paths))
        sources = [
            read_run(stack.enter_context(open(path, "r", encoding="utf-8")))
            for path in runs
        ]
        for record in heapq.merge(*sources, key=self.record_key):
            yield record


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def default_file_mode():
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


@contextmanager
def open_output(path):
    """`--output -` streams to stdout; a real path is replaced atomically."""
    if path == "-":
        stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        )
        try:
            yield stream
            stream.flush()
        finally:
            try:
                stream.flush()
                stream.detach()
            except (ValueError, OSError):
                pass
        return

    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    try:
        handle, temp_path = tempfile.mkstemp(
            dir=directory, prefix=".merge_files-", suffix=".tmp"
        )
    except OSError as exc:
        raise ToolError(
            f"cannot write output {path!r}: {exc.strerror or exc}", EXIT_ERROR
        )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, default_file_mode())
        os.replace(temp_path, target)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Partitioned output
# --------------------------------------------------------------------------

def default_dir_mode():
    mask = os.umask(0)
    os.umask(mask)
    return 0o777 & ~mask


def encode_segment(text):
    """Percent-encode UTF-8 bytes outside `[A-Za-z0-9._-]` (T44)."""
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if char in PART_SAFE:
            out.append(char)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def partition_segment(name, value, is_null):
    """One Hive-style `<col>=<val>` path segment."""
    return encode_segment(name) + "=" + encode_segment(
        NULL_SEGMENT if is_null else value
    )


class RowRenderer:
    """Renders a row into the exact text (and byte count) written to disk."""

    def __init__(self, dialect):
        self._buffer = io.StringIO(newline="")
        self._writer = dialect.writer(self._buffer)

    def render(self, row):
        self._buffer.seek(0)
        self._buffer.truncate(0)
        self._writer.writerow(row)
        return self._buffer.getvalue()


class HandlePool:
    """Keeps the number of simultaneously open part files bounded."""

    def __init__(self, limit=MAX_OPEN_PARTS):
        self.limit = limit
        self.open = OrderedDict()

    def opened(self, writer):
        self.open[id(writer)] = writer
        self.open.move_to_end(id(writer))
        while len(self.open) > self.limit:
            victim = next(iter(self.open.values()))
            if victim is writer:
                break
            victim.close()

    def touch(self, writer):
        if id(writer) in self.open:
            self.open.move_to_end(id(writer))

    def released(self, writer):
        self.open.pop(id(writer), None)


class ShardWriter:
    """One `part-00000.csv`, `part-00001.csv`, ... sequence in a directory."""

    def __init__(self, directory, header_text, max_rows, max_bytes, pool):
        self.directory = directory
        self.header_text = header_text
        self.header_bytes = len(header_text.encode("utf-8"))
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.pool = pool
        self.index = -1
        self.path = None
        self.stream = None
        self.rows = 0
        self.size = 0
        os.makedirs(directory, exist_ok=True)
        self._start_file()

    def _open(self, mode):
        try:
            self.stream = open(self.path, mode, encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(
                f"cannot write part file {self.path!r}: {exc.strerror or exc}",
                EXIT_ERROR,
            )
        self.pool.opened(self)

    def _start_file(self):
        self.index += 1
        self.rows = 0
        self.size = self.header_bytes
        self.path = os.path.join(self.directory, PART_TEMPLATE % self.index)
        self._open("w")
        self.stream.write(self.header_text)

    def _cut_needed(self, nbytes):
        if not self.rows:
            return False        # a file always takes at least one row (T48)
        if self.max_rows is not None and self.rows >= self.max_rows:
            return True
        return self.max_bytes is not None and self.size + nbytes > self.max_bytes

    def write(self, text, nbytes):
        if self._cut_needed(nbytes):
            self.close()
            self._start_file()
        elif self.stream is None:
            self._open("a")
        self.stream.write(text)
        self.rows += 1
        self.size += nbytes
        self.pool.touch(self)

    def close(self):
        if self.stream is None:
            return
        stream, self.stream = self.stream, None
        self.pool.released(self)
        stream.close()


class DirectoryOutput:
    """Stage the whole tree in a sibling temp directory, then move it in."""

    def __init__(self, target):
        self.target = os.path.abspath(target)
        self.parent = os.path.dirname(self.target) or "."
        self.temp = None

    def check(self):
        """Reject an unusable `--output` before any work is done."""
        if os.path.exists(self.target) and not os.path.isdir(self.target):
            raise ToolError(
                f"--output must be a directory when partitioning: "
                f"{self.target!r} exists and is not a directory",
                EXIT_USAGE,
            )

    def begin(self):
        self.check()
        try:
            os.makedirs(self.parent, exist_ok=True)
            self.temp = tempfile.mkdtemp(dir=self.parent, prefix=".merge_files-",
                                         suffix=".tmp")
        except OSError as exc:
            raise ToolError(
                f"cannot create output directory {self.target!r}: "
                f"{exc.strerror or exc}",
                EXIT_ERROR,
            )
        return self.temp

    def commit(self):
        try:
            os.chmod(self.temp, default_dir_mode())
        except OSError:
            pass
        try:
            os.rename(self.temp, self.target)
            self.temp = None
            return
        except OSError:
            pass
        # The target already exists and is not empty: move the staged tree in
        # entry by entry, replacing same-named files (T42).
        try:
            self._merge_into(self.temp, self.target)
        except OSError as exc:
            raise ToolError(
                f"cannot write output directory {self.target!r}: "
                f"{exc.strerror or exc}",
                EXIT_ERROR,
            )
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp = None

    @staticmethod
    def _merge_into(source, target):
        os.makedirs(target, exist_ok=True)
        for name in sorted(os.listdir(source)):
            src = os.path.join(source, name)
            dst = os.path.join(target, name)
            if os.path.isdir(src) and not os.path.islink(src):
                DirectoryOutput._merge_into(src, dst)
            else:
                os.replace(src, dst)

    def abort(self):
        if self.temp is not None:
            shutil.rmtree(self.temp, ignore_errors=True)
            self.temp = None


def write_partitioned(target, header, records, dialect, partitioned_rows,
                      max_rows, max_bytes):
    """Write the sorted stream as a `part-xxxxx.csv` tree under `target`."""
    output = DirectoryOutput(target)
    root = output.begin()
    writers = OrderedDict()
    try:
        renderer = RowRenderer(dialect)
        header_text = renderer.render(header)
        pool = HandlePool()

        def writer_for(segments):
            writer = writers.get(segments)
            if writer is None:
                directory = os.path.join(root, *segments)
                writer = ShardWriter(directory, header_text, max_rows, max_bytes,
                                     pool)
                writers[segments] = writer
            return writer

        if not partitioned_rows:
            # Sharding alone always produces at least a header-only part (T43).
            writer_for(())
        for record in records:
            row = record[2]
            segments = tuple(record[3]) if partitioned_rows else ()
            text = renderer.render(row)
            writer_for(segments).write(text, len(text.encode("utf-8")))
        for writer in writers.values():
            writer.close()
        output.commit()
    except BaseException:
        for writer in writers.values():
            try:
                writer.close()
            except OSError:
                pass
        output.abort()
        raise


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

class Parser(argparse.ArgumentParser):
    """argparse, but its usage errors travel the same path as ours."""

    def error(self, message):
        raise ToolError(message, EXIT_USAGE)


def build_parser():
    parser = Parser(
        prog=PROG,
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True, metavar="PATH|-",
                        help="output CSV path, or '-' for stdout")
    parser.add_argument("--key", required=True, action="append", metavar="COL[,COL...]",
                        help="sort key column(s); may be repeated")
    parser.add_argument("--partition-by", dest="partition_by", action="append",
                        metavar="COL[,COL...]",
                        help="write a Hive-style directory per value combination")
    parser.add_argument("--max-rows-per-file", dest="max_rows_per_file", type=int,
                        default=None, metavar="INT",
                        help="cut each output file after INT data rows")
    parser.add_argument("--max-bytes-per-file", dest="max_bytes_per_file", type=int,
                        default=None, metavar="INT",
                        help="cut each output file at INT bytes (header included)")
    parser.add_argument("--desc", action="store_true",
                        help="sort every key in descending order")
    parser.add_argument("--schema", metavar="SCHEMA_JSON",
                        help="JSON file giving the exact output schema and order")
    parser.add_argument("--type-alias-file", dest="type_alias_file",
                        metavar="ALIASES_JSON",
                        help="JSON file of extra type aliases")
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict",
                        help="type inference mode when --schema is absent")
    parser.add_argument("--schema-strategy", dest="schema_strategy",
                        choices=("authoritative", "consensus", "union"),
                        default="authoritative",
                        help="how to reconcile conflicting types across inputs")
    parser.add_argument("--on-type-error", dest="on_type_error",
                        choices=("coerce-null", "fail", "keep-string"),
                        default="coerce-null", help="behaviour on a failed cast")
    parser.add_argument("--memory-limit-mb", dest="memory_limit_mb", type=int,
                        default=DEFAULT_MEMORY_LIMIT_MB, metavar="INT",
                        help="approximate in-memory budget before spilling to disk")
    parser.add_argument("--temp-dir", dest="temp_dir", metavar="PATH",
                        help="directory for intermediate spill files")
    parser.add_argument("--csv-quotechar", dest="csv_quotechar", default='"',
                        metavar="CHAR", help="CSV quote character (default: \")")
    parser.add_argument("--csv-escapechar", dest="csv_escapechar", default=None,
                        metavar="CHAR",
                        help="CSV escape character (default: doubled quotes)")
    parser.add_argument("--csv-null-literal", dest="csv_null_literal", default="",
                        metavar="STRING", help="text used for null cells")
    parser.add_argument("--input-format", dest="input_format",
                        choices=("auto",) + INPUT_FORMATS, default="auto",
                        help="input format; 'auto' detects per file")
    parser.add_argument("--compression", choices=("auto", "none", "gzip"),
                        default="auto", help="input compression")
    parser.add_argument("--parquet-row-group-bytes", dest="parquet_row_group_bytes",
                        type=int, default=DEFAULT_ROW_GROUP_BYTES, metavar="INT",
                        help="advisory batch size for streamed Parquet reads")
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


def parse_column_list(values, flag):
    """`--key`/`--partition-by`: comma-separated field paths, deduplicated."""
    paths, seen = [], set()
    for value in values:
        for part in split_field_paths(value):
            text = part.strip()
            if not text:
                raise ToolError(
                    f"{flag} must name at least one non-empty column", EXIT_USAGE
                )
            if text in seen:
                continue
            seen.add(text)
            paths.append(parse_field_path(text, flag))
    if not paths:
        raise ToolError(f"{flag} must name at least one column", EXIT_USAGE)
    return paths


def bind_paths(paths, columns, positions, what):
    """Attach each path to its column and check that it lands on a primitive."""
    for path in paths:
        if path.text in positions:
            # A column whose literal name contains dots wins (AMBIGUITIES T59).
            path.slot = positions[path.text]
            path.segments = [path.text]
        elif path.column in positions:
            path.slot = positions[path.column]
        else:
            raise ToolError(
                f"{what} column {path.column!r} is not present in the resolved "
                f"schema ({', '.join(c.name for c in columns) or 'no columns'})",
                EXIT_SCHEMA,
            )
        path.leaf = resolve_path_type(columns[path.slot].type, path, what)
    return paths


def make_null_test(literal):
    if literal == "":
        return lambda text: text == ""
    return lambda text: text == "" or text == literal


def cast_cell(value, type_name, typed, is_null):
    """Cast one cell into `type_name`; returns (status, value, source text)."""
    if value is MISSING or value is None:
        return NULL, None, None
    if isinstance(value, str):
        # Typed string values go through the text caster too (T39).
        if is_null(value):
            return NULL, None, None
        parsed = PARSERS[type_name](value)
        if parsed is None:
            return ERR, None, value
        return OK, parsed, value
    if not typed:
        text = str(value)
        parsed = PARSERS[type_name](text)
        if parsed is None:
            return ERR, None, text
        return OK, parsed, text
    parsed = cast_typed(value, type_name)
    if parsed is None:
        return ERR, None, format_natural(value)
    return OK, parsed, format_natural(value)


def cast_primitive(value, type_name, typed, caster, name):
    """Cast one flat cell; returns the typed value, None, or a Kept string."""
    if isinstance(value, (dict, list)):
        # "If schema declares flat type but input has object/array".
        return caster.failed(Caster.stringify(value), type_name, [name])
    status, casted, text = cast_cell(value, type_name, typed, caster.is_null)
    if status == NULL:
        return None
    if status == OK:
        return casted
    return caster.failed(text, type_name, [name])


def cast_column(value, type_node, typed, caster, name):
    """Cast one cell of a nested (or `json`) column into JSON-shaped values."""
    if value is MISSING or value is None:
        return None
    if not typed and isinstance(value, str):
        # "CSV/TSV: Cell must contain single JSON literal ... Empty cell ->
        # null; Invalid JSON -> handled per --on-type-error".
        if caster.is_null(value):
            return None
        try:
            parsed = json.loads(value)
        except ValueError:
            return caster.failed(value, type_node, [name])
        return caster.cast(parsed, type_node, [name])
    return caster.cast(value, type_node, [name])


def run(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if len(args.csv_quotechar) != 1:
        raise ToolError("--csv-quotechar must be exactly one character", EXIT_USAGE)
    if args.csv_escapechar is not None and len(args.csv_escapechar) != 1:
        raise ToolError("--csv-escapechar must be exactly one character", EXIT_USAGE)
    if args.memory_limit_mb <= 0:
        raise ToolError("--memory-limit-mb must be a positive integer", EXIT_USAGE)
    if args.parquet_row_group_bytes <= 0:
        raise ToolError(
            "--parquet-row-group-bytes must be a positive integer", EXIT_USAGE
        )
    if args.temp_dir is not None and not os.path.isdir(args.temp_dir):
        raise ToolError(f"--temp-dir is not a directory: {args.temp_dir!r}", EXIT_USAGE)
    for flag, limit in (("--max-rows-per-file", args.max_rows_per_file),
                        ("--max-bytes-per-file", args.max_bytes_per_file)):
        if limit is not None and limit <= 0:
            raise ToolError(f"{flag} must be a positive integer", EXIT_USAGE)

    key_paths = parse_column_list(args.key, "--key")
    partition_paths = (
        parse_column_list(args.partition_by, "--partition-by")
        if args.partition_by else []
    )
    partitioned = bool(
        partition_paths
        or args.max_rows_per_file is not None
        or args.max_bytes_per_file is not None
    )
    if partitioned:
        if args.output == "-":
            raise ToolError(
                "--output must be a directory path when partitioning, not '-'",
                EXIT_USAGE,
            )
        # Reject an unusable target before a single input byte is read.
        DirectoryOutput(args.output).check()
    null_literal = args.csv_null_literal
    is_null = make_null_test(null_literal)
    dialect = Dialect(args.csv_quotechar, args.csv_escapechar)
    budget = max(int(args.memory_limit_mb * 1024 * 1024 * 0.6), 256 * 1024)
    options = Options(dialect, is_null, args.parquet_row_group_bytes, budget)

    sources = build_sources(args.inputs, args.input_format, args.compression, options)

    # --- resolve the schema -------------------------------------------------
    aliases = load_aliases(args.type_alias_file)
    if args.schema is not None:
        columns = load_schema(args.schema, aliases)
        declared = {column.name: column.type for column in columns}
        for source in sources:
            source.schema = declared
    else:
        # "Schema Inference (Unchanged, Flat-Only)": nested input is rejected.
        columns = infer_schema(sources, args.infer, args.schema_strategy, is_null)

    positions = {column.name: i for i, column in enumerate(columns)}
    bind_paths(key_paths, columns, positions, "key")
    bind_paths(partition_paths, columns, positions, "partition")
    types = [column.type for column in columns]
    header = [column.name for column in columns]
    caster = Caster(is_null, args.on_type_error)

    store = RunStore(args.temp_dir)
    record_key = make_record_key(args.desc)
    sorter = Sorter(budget, store, record_key)

    try:
        seq = 0
        for source in sources:
            typed = source.typed
            for locator, record in source.iter_records():
                caster.at(locator[0], locator[1])
                out_row = []
                values = []
                for slot, name in enumerate(header):
                    type_node = types[slot]
                    value = record.get(name, MISSING)
                    if is_primitive(type_node):
                        node = cast_primitive(value, type_node, typed, caster, name)
                        cell = (
                            null_literal if node is None
                            else str(node) if isinstance(node, Kept)
                            else format_value(node, type_node)
                        )
                    else:
                        node = cast_column(value, type_node, typed, caster, name)
                        # "If entire column value is null -> emit CSV null
                        # literal"; otherwise the canonical JSON text.
                        cell = (
                            null_literal if node is None
                            else str(node) if isinstance(node, Kept)
                            else json_text(node)
                        )
                    out_row.append(cell)
                    values.append(node)
                key = [
                    path_fragment(lookup_path(values[path.slot], path.segments[1:]),
                                  path.leaf, path, "key")
                    for path in key_paths
                ]
                segments = None
                if partition_paths:
                    segments = []
                    for path in partition_paths:
                        text = path_text_value(
                            lookup_path(values[path.slot], path.segments[1:]),
                            path.leaf, path, "partition",
                        )
                        segments.append(partition_segment(
                            path.text, text or "", text is None))
                sorter.add(key, seq, out_row, segments)
                seq += 1

        with ExitStack() as stack:
            records = sorter.sorted_records(stack)
            if partitioned:
                write_partitioned(args.output, header, records, dialect,
                                  bool(partition_paths), args.max_rows_per_file,
                                  args.max_bytes_per_file)
            else:
                out_stream = stack.enter_context(open_output(args.output))
                writer = dialect.writer(out_stream)
                writer.writerow(header)
                for record in records:
                    writer.writerow(record[2])
                out_stream.flush()
    finally:
        store.cleanup()
    return EXIT_OK


def main(argv=None):
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except ToolError as exc:
        # "ERR <n> <message>", one line, as the spec spells out (T53).
        sys.stderr.write(f"ERR {exc.code} {exc}\n")
        return exc.code
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Merge heterogeneous tabular inputs into a single schema-aligned, sorted CSV.

Supported input formats are CSV, TSV, JSON Lines (NDJSON) and Parquet, each
optionally gzip-compressed.  A provided ``--schema`` may declare nested
columns (``struct``, ``array<T>``, ``map<string,T>`` or free-form ``json``);
such columns are cast recursively and rendered as canonical minified JSON in
their CSV cell, while ``--key`` / ``--partition-by`` address the primitives
inside them through dotted / bracketed field paths (``user.id``,
``items.0.qty``, ``attrs["country"]``).  Without ``--schema`` the inferred
schema stays flat and nested JSONL/Parquet input is rejected.

Every input is streamed, reconciled against a resolved output schema, cast
cell by cell, buffered until the memory budget is reached, spilled to sorted
temporary run files and finally k-way merged onto the output stream.  Peak
memory therefore stays bounded regardless of how large the inputs are.

The merged stream is written either as one CSV file (or stdout), or -- when any
partitioning flag is given -- as a directory of ``part-xxxxx.csv`` shards,
optionally nested under Hive-style ``<col>=<value>`` partition directories.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import io
import json
import math
import os
import re
import shutil
import sys
import zlib
import tempfile
from datetime import date as date_cls
from datetime import datetime
from datetime import time as time_cls
from datetime import timedelta, timezone
from decimal import Decimal

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

# Exit codes.
EXIT_OK = 0
EXIT_USAGE = 2  # bad invocation, unreadable input, undetectable format
EXIT_SCHEMA = 3  # schema problems (including unknown --key columns)
EXIT_TYPE = 4  # cast failure under --on-type-error=fail
EXIT_MALFORMED = 5  # malformed input / dialect or compression mismatch
EXIT_UNSUPPORTED = 6  # nested (non-flat) JSONL or Parquet structures

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

EXT_FORMAT = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}

RAW_FORMATS = ("csv", "tsv")
TYPED_FORMATS = ("jsonl", "parquet")

# Precedence used by --schema-strategy=authoritative: typed sources first.
FORMAT_RANK = {"parquet": 0, "jsonl": 1, "csv": 2, "tsv": 2}


class UserError(Exception):
    """Fatal, user-facing error: reported on stderr with a non-zero exit."""

    def __init__(self, message, code=EXIT_USAGE):
        super().__init__(message)
        self.code = code


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
    raise UserError("unknown type %r" % typ, EXIT_SCHEMA)


# --------------------------------------------------------------------------
# Typed (JSONL / Parquet) value handling
# --------------------------------------------------------------------------


def normalize_typed(value):
    """Reduce a JSONL/Parquet value to one of the shapes the caster handles."""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def normalize_json_number(value):
    """JSON numbers prefer ``int`` when integral and inside the int64 range."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if INT64_MIN <= value <= INT64_MAX:
            return value
        return float(value)
    if isinstance(value, float):
        if value.is_integer() and INT64_MIN <= value <= INT64_MAX:
            return int(value)
        return value
    return value


def typed_to_string(value):
    """Canonical string rendering of a typed value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, date_cls):
        return value.isoformat()
    if isinstance(value, time_cls):
        return value.isoformat()
    return str(value)


def cast_value(typ, value):
    """Cast an already-typed JSONL/Parquet value to ``typ``.

    Returns ``(ok, output_text, sort_key)`` exactly like :func:`cast_cell`.
    """
    if isinstance(value, (dict, list, tuple)):
        # A nested value can never satisfy a flat column; --on-type-error decides.
        return False, None, None
    value = normalize_typed(value)

    if isinstance(value, str):
        # A typed string still has to satisfy the target type's text rules.
        return cast_cell(typ, value)

    if typ == "string":
        text = typed_to_string(value)
        return True, text, [1, 1, text]

    if typ == "int":
        if isinstance(value, bool):
            number = 1 if value else 0
        elif isinstance(value, int):
            number = value
        elif isinstance(value, float):
            if not value.is_integer():
                return False, None, None
            number = int(value)
        else:
            return False, None, None
        return True, str(number), [1, 0, number]

    if typ == "float":
        if isinstance(value, bool):
            number = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            number = float(value)
        else:
            return False, None, None
        return True, repr(number), [1, 0, number]

    if typ == "bool":
        if isinstance(value, bool):
            flag = value
        elif isinstance(value, int) and value in (0, 1):
            flag = bool(value)
        elif isinstance(value, float) and value in (0.0, 1.0):
            flag = bool(value)
        else:
            return False, None, None
        return True, ("true" if flag else "false"), [1, 0, 1 if flag else 0]

    if typ == "date":
        if isinstance(value, datetime):
            iso = value.strftime("%Y-%m-%d")
        elif isinstance(value, date_cls):
            iso = value.isoformat()
        else:
            return False, None, None
        return True, iso, [1, 1, iso]

    if typ == "timestamp":
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date_cls):
            dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        else:
            return False, None, None
        return True, format_timestamp(dt), [1, 0, dt.timestamp()]

    raise UserError("unknown type %r" % typ, EXIT_SCHEMA)


# --------------------------------------------------------------------------
# Nested type model
# --------------------------------------------------------------------------

# A type is either a primitive name (``"int"``) or a tuple:
#   ("struct", ((name, type), ...))   ordered, uniquely named fields
#   ("array", element_type)           homogeneous elements
#   ("map", value_type)               string keys, homogeneous values
#   ("json",)                         free-form JSON, accepted as-is
JSON_TYPE = ("json",)

KIND_NAMES = ("struct", "array", "map")

# Always-present, case-insensitive type aliases.
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

# Keys of a type object that carry parameters rather than naming a kind.
PARAM_KEYS = frozenset(
    (
        "name",
        "fields",
        "field",
        "columns",
        "element",
        "elementtype",
        "items",
        "item",
        "key",
        "keytype",
        "value",
        "valuetype",
        "values",
        "type",
        "nullable",
        "doc",
        "description",
        "metadata",
    )
)

INDEX_RE = re.compile(r"^\d+$")


def is_primitive(typ):
    return isinstance(typ, str)


def type_kind(typ):
    return "primitive" if isinstance(typ, str) else typ[0]


def type_label(typ):
    """Human-readable rendering of a type, used in diagnostics."""
    if isinstance(typ, str):
        return typ
    kind = typ[0]
    if kind == "json":
        return "json"
    if kind == "array":
        return "array<%s>" % type_label(typ[1])
    if kind == "map":
        return "map<string,%s>" % type_label(typ[1])
    if kind == "struct":
        return "struct<%s>" % ",".join(
            "%s:%s" % (name, type_label(field)) for name, field in typ[1]
        )
    return str(typ)


VALID_TYPE_HELP = ", ".join(VALID_TYPES) + ", struct, array<T>, map<string,T>, json"


def invalid_type_error(spec, where):
    location = " for %s" % where if where else ""
    return UserError(
        "invalid type %r%s (valid: %s)" % (spec, location, VALID_TYPE_HELP), EXIT_SCHEMA
    )


def alias_cycle_error(name):
    return UserError("ERR 2 type alias cycle detected for %r" % name, EXIT_USAGE)


def split_generic(text):
    """Split ``head<a,b>`` into ``("head", ["a", "b"])`` or return ``None``."""
    start = text.find("<")
    if start < 0 or not text.endswith(">"):
        return None
    head = text[:start].strip()
    if not head:
        return None
    args = []
    current = []
    depth = 0
    for char in text[start + 1 : -1]:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth < 0:
                return None
        elif char == "," and depth == 0:
            args.append("".join(current))
            current = []
            continue
        current.append(char)
    if depth != 0:
        return None
    args.append("".join(current))
    return head, args


def resolve_head_name(name, aliases, seen):
    """Resolve an alias chain for a name used as a type constructor head."""
    current = name.strip().lower()
    chain = set(seen)
    while current in aliases:
        if current in chain:
            raise alias_cycle_error(current)
        chain.add(current)
        target = aliases[current]
        if not isinstance(target, str):
            return None
        target = target.strip()
        if "<" in target:
            # A parameterized alias cannot serve as a bare constructor head.
            return None
        current = target.lower()
    return current


def resolve_type_string(text, aliases, seen=frozenset(), where=None):
    """Resolve a textual type (possibly aliased or parameterized) to a type."""
    if not isinstance(text, str):
        raise invalid_type_error(text, where)
    spec = text.strip()
    if not spec:
        raise invalid_type_error(text, where)

    generic = split_generic(spec)
    if generic is not None:
        head_text, args = generic
        head = resolve_head_name(head_text, aliases, seen)
        args = [arg.strip() for arg in args]
        if head == "array":
            if len(args) != 1:
                raise invalid_type_error(spec, where)
            return ("array", resolve_type_string(args[0], aliases, frozenset(), where))
        if head == "map":
            if len(args) == 1:
                key_spec, value_spec = "string", args[0]
            elif len(args) == 2:
                key_spec, value_spec = args
            else:
                raise invalid_type_error(spec, where)
            if resolve_type_string(key_spec, aliases, frozenset(), where) != "string":
                raise UserError(
                    "map keys must be of type string (in %r)" % spec, EXIT_SCHEMA
                )
            return ("map", resolve_type_string(value_spec, aliases, frozenset(), where))
        if head == "struct":
            fields = []
            names = set()
            for arg in args:
                name, sep, field_spec = arg.partition(":")
                name = name.strip()
                if not name or not sep:
                    raise invalid_type_error(spec, where)
                if name in names:
                    raise UserError(
                        "duplicate field %r in struct %r" % (name, spec), EXIT_SCHEMA
                    )
                names.add(name)
                fields.append(
                    (
                        name,
                        resolve_type_string(
                            field_spec, aliases, frozenset(), 'field "%s"' % name
                        ),
                    )
                )
            if not fields:
                return JSON_TYPE
            return ("struct", tuple(fields))
        raise invalid_type_error(spec, where)

    lowered = spec.lower()
    if lowered in aliases:
        if lowered in seen:
            raise alias_cycle_error(lowered)
        target = aliases[lowered]
        if not isinstance(target, str):
            return parse_type_node(target, aliases, where)
        return resolve_type_string(target, aliases, seen | {lowered}, where)
    if lowered in VALID_TYPES:
        return lowered
    if lowered in ("struct", "json"):
        # A struct without declared fields accepts any JSON value.
        return JSON_TYPE
    raise invalid_type_error(spec, where)


def lower_keys(mapping):
    out = {}
    for key, value in mapping.items():
        if isinstance(key, str):
            out[key.strip().lower()] = value
    return out


def pick_key(mapping, names):
    for name in names:
        if name in mapping:
            return mapping[name], True
    return None, False


def parse_struct_fields(spec, aliases, where):
    """Parse a struct's field list into an ordered tuple of (name, type)."""
    if isinstance(spec, dict):
        entries = list(spec.items())
    elif isinstance(spec, list):
        entries = []
        for entry in spec:
            if isinstance(entry, str):
                entries.append((entry, "string"))
            elif isinstance(entry, dict):
                lowered = lower_keys(entry)
                if "name" in lowered:
                    entries.append((lowered["name"], lowered.get("type", "string")))
                elif len(entry) == 1:
                    entries.extend(entry.items())
                else:
                    raise UserError("struct field is missing a name", EXIT_SCHEMA)
            else:
                raise UserError(
                    "invalid struct field entry: %r" % (entry,), EXIT_SCHEMA
                )
    else:
        raise UserError("struct fields must be a list of fields", EXIT_SCHEMA)

    fields = []
    seen = set()
    for name, field_spec in entries:
        if not isinstance(name, str) or not name:
            raise UserError("struct field is missing a name", EXIT_SCHEMA)
        if name in seen:
            raise UserError("duplicate field %r in struct" % name, EXIT_SCHEMA)
        seen.add(name)
        fields.append((name, parse_type_node(field_spec, aliases, 'field "%s"' % name)))
    if not fields:
        return None
    return tuple(fields)


def build_kind_type(kind, body, params, aliases, where):
    """Build a struct/array/map type from its body (and sibling parameters)."""
    same = body is params
    body_map = lower_keys(body) if isinstance(body, dict) else {}

    if kind == "struct":
        spec, found = pick_key(body_map, ("fields", "field", "columns"))
        if not found and isinstance(body, list):
            spec, found = body, True
        if not found:
            spec, found = pick_key(params, ("fields", "field", "columns"))
        if not found:
            return JSON_TYPE
        fields = parse_struct_fields(spec, aliases, where)
        if fields is None:
            return JSON_TYPE
        return ("struct", fields)

    if kind == "array":
        names = ["element", "elementtype", "items", "item", "value", "valuetype"]
        if not same:
            names.append("type")
        spec, found = pick_key(body_map, names)
        if not found and isinstance(body, (str, list)):
            spec, found = body, True
        if not found:
            spec, found = pick_key(params, names)
        if not found:
            raise UserError("array type requires an element type", EXIT_SCHEMA)
        return ("array", parse_type_node(spec, aliases, where))

    # map
    value_names = ["value", "valuetype", "values", "element", "elementtype"]
    if not same:
        value_names.append("type")
    spec, found = pick_key(body_map, value_names)
    if not found and isinstance(body, str):
        spec, found = body, True
    if not found:
        spec, found = pick_key(params, value_names)
    if not found:
        raise UserError("map type requires a value type", EXIT_SCHEMA)
    key_spec, has_key = pick_key(body_map, ("key", "keytype"))
    if not has_key:
        key_spec, has_key = pick_key(params, ("key", "keytype"))
    if has_key and parse_type_node(key_spec, aliases, where) != "string":
        raise UserError("map keys must be of type string", EXIT_SCHEMA)
    return ("map", parse_type_node(spec, aliases, where))


def parse_type_node(node, aliases, where=None):
    """Parse a type given either as a string or as a JSON object."""
    if isinstance(node, str):
        return resolve_type_string(node, aliases, frozenset(), where)
    if not isinstance(node, dict):
        raise invalid_type_error(node, where)

    lowered = lower_keys(node)
    kinds = {}
    for key, value in lowered.items():
        if key in PARAM_KEYS:
            continue
        head = resolve_head_name(key, aliases, frozenset())
        if head in KIND_NAMES:
            kinds.setdefault(head, value)
    for kind in KIND_NAMES:
        if kind in kinds:
            return build_kind_type(kind, kinds[kind], lowered, aliases, where)

    if "type" in lowered:
        inner = lowered["type"]
        if isinstance(inner, str):
            head = resolve_head_name(inner, aliases, frozenset())
            if head in KIND_NAMES and split_generic(inner.strip()) is None:
                return build_kind_type(head, lowered, lowered, aliases, where)
            return resolve_type_string(inner, aliases, frozenset(), where)
        return parse_type_node(inner, aliases, where)
    raise invalid_type_error(node, where)


def read_json_spec(spec, label, code=EXIT_USAGE, file_label=None):
    """Read a JSON document given either as a path or as inline JSON text."""
    text = None
    if os.path.exists(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as handle:
                text = handle.read()
        except OSError as exc:
            raise UserError("cannot read %s %s: %s" % (label, spec, exc.strerror or exc))
    else:
        stripped = spec.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            text = stripped
        else:
            raise UserError("%s not found: %s" % (file_label or label, spec))
    try:
        return json.loads(text)
    except ValueError as exc:
        raise UserError("invalid %s JSON: %s" % (label, exc), code)


def load_aliases(spec):
    """Build the alias table: built-ins plus an optional user alias file."""
    aliases = dict(BUILTIN_ALIASES)
    if spec:
        data = read_json_spec(spec, "type alias file", EXIT_USAGE)
        table = data.get("aliases", data) if isinstance(data, dict) else data
        if not isinstance(table, dict):
            raise UserError(
                "type alias file must contain an 'aliases' object", EXIT_USAGE
            )
        for name, target in table.items():
            if not isinstance(name, str) or not name.strip():
                raise UserError("invalid type alias name: %r" % (name,), EXIT_USAGE)
            if isinstance(target, str):
                if not target.strip():
                    raise UserError(
                        "invalid target for type alias %r" % name, EXIT_USAGE
                    )
                aliases[name.strip().lower()] = target.strip()
            elif isinstance(target, dict):
                aliases[name.strip().lower()] = target
            else:
                raise UserError("invalid target for type alias %r" % name, EXIT_USAGE)

    # Resolve every alias once up front so cycles are reported deterministically
    # even when the offending alias is never referenced by the schema.
    for name in list(aliases):
        try:
            resolve_type_string(name, aliases, frozenset(), None)
        except UserError as exc:
            if exc.code == EXIT_USAGE:
                raise
    return aliases


# --------------------------------------------------------------------------
# Nested values: casting and canonical JSON encoding
# --------------------------------------------------------------------------


def json_scalar(typ, text):
    """The JSON representation of a cast primitive, given its output text."""
    if typ == "int":
        return int(text)
    if typ == "float":
        number = float(text)
        return number if math.isfinite(number) else None
    if typ == "bool":
        return text == "true"
    return text


def cast_primitive(typ, value, raw):
    """Cast one primitive value: ``(ok, text, json_value, sort_key)``."""
    if raw:
        ok, text, key = cast_cell(typ, value)
    else:
        ok, text, key = cast_value(typ, value)
    if not ok:
        return False, None, None, None
    return True, text, json_scalar(typ, text), key


def str_key(key):
    if isinstance(key, str):
        return key
    if key is None:
        return "null"
    return typed_to_string(normalize_typed(key))


def json_ready(value):
    """Make an arbitrary Python value JSON-encodable without losing shape."""
    if isinstance(value, dict):
        return {str_key(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return typed_to_string(normalize_typed(value))


def canonical_json(value):
    """Minified RFC 8259 JSON; caller guarantees the intended key order."""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError:
        return json.dumps(
            json_ready(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )


def stringify_original(value):
    """The ``keep-string`` rendering of a value that failed to cast."""
    if isinstance(value, (dict, list, tuple)):
        return canonical_json(json_ready(value))
    if value is None:
        return "null"
    return typed_to_string(normalize_typed(value))


def normalize_json_value(value):
    """Normalize a free-form (``json``) value: object keys sorted, no casting."""
    if isinstance(value, dict):
        items = sorted(((str_key(k), v) for k, v in value.items()), key=lambda kv: kv[0])
        return {key: normalize_json_value(item) for key, item in items}
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item) for item in value]
    if value is None or isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        # RFC 8259 has no infinity/NaN; anything else is kept verbatim.
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        # Free-form JSON is not cast, so wide integers keep full precision.
        return value
    return typed_to_string(normalize_typed(value))


def map_items(value):
    """Interpret ``value`` as map entries, or return ``None``."""
    if isinstance(value, dict):
        return [(str_key(key), item) for key, item in value.items()]
    if isinstance(value, (list, tuple)):
        entries = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                entries.append((str_key(item[0]), item[1]))
            else:
                return None
        return entries
    return None


def shape_matches(typ, value):
    kind = type_kind(typ)
    if kind == "struct":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, (list, tuple))
    if kind == "map":
        return map_items(value) is not None
    return True


class CastContext:
    """Per-row context for nested casting: error mode plus provenance."""

    __slots__ = ("on_type_error", "null_literal", "file", "line")

    def __init__(self, on_type_error, null_literal):
        self.on_type_error = on_type_error
        self.null_literal = null_literal
        self.file = ""
        self.line = 0

    def failed(self, typ, value, field, original=None):
        """Apply --on-type-error to one failed (possibly nested) field."""
        if self.on_type_error == "fail":
            shown = original if original is not None else stringify_original(value)
            raise UserError(
                'ERR 4 cannot cast "%s" to %s in field "%s" (file=%s line=%s)'
                % (shown, type_label(typ), field, self.file, self.line),
                EXIT_TYPE,
            )
        if self.on_type_error == "keep-string":
            return original if original is not None else stringify_original(value)
        return None


def cast_nested_value(typ, value, field, ctx):
    """Recursively cast ``value`` to ``typ``, returning canonical JSON data."""
    if value is None:
        return None
    kind = type_kind(typ)

    if kind == "json":
        return normalize_json_value(value)

    if kind == "primitive":
        if isinstance(value, str) and ctx.null_literal and value == ctx.null_literal:
            return None
        if isinstance(value, (dict, list, tuple)):
            return ctx.failed(typ, value, field)
        ok, _text, json_value, _key = cast_primitive(typ, value, False)
        if not ok:
            return ctx.failed(typ, value, field)
        return json_value

    if kind == "struct":
        if not isinstance(value, dict):
            return ctx.failed(typ, value, field)
        out = {}
        for name, field_type in typ[1]:
            out[name] = cast_nested_value(
                field_type, value.get(name), field + "." + name, ctx
            )
        return out

    if kind == "array":
        if not isinstance(value, (list, tuple)):
            return ctx.failed(typ, value, field)
        element_type = typ[1]
        return [
            cast_nested_value(element_type, item, "%s.%d" % (field, index), ctx)
            for index, item in enumerate(value)
        ]

    if kind == "map":
        entries = map_items(value)
        if entries is None:
            return ctx.failed(typ, value, field)
        value_type = typ[1]
        out = {}
        for key, item in sorted(entries, key=lambda entry: entry[0]):
            out[key] = cast_nested_value(
                value_type, item, '%s["%s"]' % (field, key), ctx
            )
        return out

    raise UserError("unknown type %r" % (typ,), EXIT_SCHEMA)


_INVALID = object()


def cast_nested_cell(typ, cell, raw, field, ctx):
    """Cast one whole nested/``json`` column cell.

    Returns ``(text, tree)``: the CSV cell content (``None`` for a null cell)
    and the cast value tree used for field-path lookups.
    """
    value = cell
    original = None
    if raw:
        original = cell
        try:
            value = json.loads(cell.strip())
        except ValueError:
            value = _INVALID
    elif isinstance(value, str) and type_kind(typ) != "json":
        original = value
        try:
            value = json.loads(value.strip())
        except ValueError:
            value = _INVALID
    if value is _INVALID:
        return ctx.failed(typ, cell, field, original=original), None
    if value is None:
        return None, None
    if not shape_matches(typ, value):
        return ctx.failed(typ, value, field, original=original), None
    tree = cast_nested_value(typ, value, field, ctx)
    if tree is None:
        return None, None
    return canonical_json(tree), tree


# --------------------------------------------------------------------------
# Field paths (dotted / bracketed) for --key and --partition-by
# --------------------------------------------------------------------------


def split_paths(text):
    """Split a comma-separated list of field paths, honouring ``["..."]``."""
    parts = []
    current = []
    depth = 0
    quote = None
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if quote:
            current.append(char)
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def path_error(text):
    return UserError("invalid field path %r" % text, EXIT_SCHEMA)


def unquote_bracket_key(inner, text):
    quote = inner[0]
    out = []
    index = 1
    while index < len(inner):
        char = inner[index]
        if char == "\\" and index + 1 < len(inner):
            out.append(inner[index + 1])
            index += 2
            continue
        if char == quote:
            if index != len(inner) - 1:
                raise path_error(text)
            return "".join(out)
        out.append(char)
        index += 1
    raise path_error(text)


def parse_field_path(text):
    """Parse ``user.id`` / ``items.0.qty`` / ``attrs["country"]`` into segments.

    Segments are ``("name", str)``, ``("index", int)`` or ``("key", str)``;
    a plain dotted segment stays ``"name"`` until the schema says otherwise.
    """
    spec = text.strip()
    if not spec:
        raise path_error(text)
    segments = []
    buffer = []
    # True right after a ``[...]`` segment, where a following "." is optional.
    bracketed = False

    def flush():
        if buffer:
            segments.append(("name", "".join(buffer)))
            del buffer[:]
            return True
        return False

    index = 0
    length = len(spec)
    while index < length:
        char = spec[index]
        if char == ".":
            if not flush() and not bracketed:
                raise path_error(text)
            bracketed = False
            index += 1
            if index >= length:
                raise path_error(text)
            continue
        if char == "[":
            flush()
            bracketed = True
            if not segments:
                raise path_error(text)
            end = spec.find("]", index + 1)
            if end < 0:
                raise path_error(text)
            inner = spec[index + 1 : end].strip()
            if not inner:
                raise path_error(text)
            if inner[0] in ("'", '"'):
                segments.append(("key", unquote_bracket_key(inner, text)))
            elif INDEX_RE.match(inner):
                segments.append(("index", int(inner)))
            else:
                segments.append(("key", inner))
            index = end + 1
            continue
        buffer.append(char)
        bracketed = False
        index += 1
    flush()
    if not segments or segments[0][0] != "name":
        raise path_error(text)
    return segments


def path_label(segments):
    """Normalized dotted label, used for Hive partition directory names."""
    return ".".join(str(value) for _kind, value in segments)


class FieldPath:
    """A resolved ``--key`` / ``--partition-by`` reference."""

    __slots__ = ("text", "label", "column", "steps", "leaf_type")

    def __init__(self, text, label, column, steps, leaf_type):
        self.text = text
        self.label = label
        self.column = column
        self.steps = steps
        self.leaf_type = leaf_type


def primitive_error(text, kind):
    return UserError(
        'ERR 3 %s column "%s" does not resolve to a primitive' % (kind, text),
        EXIT_SCHEMA,
    )


def path_root(text):
    """The output column a path refers to, without validating the remainder."""
    try:
        segments = parse_field_path(text)
    except UserError:
        return text
    return segments[0][1]


def resolve_field_path(text, names, types, kind):
    """Resolve one field path against the output schema."""
    if text in names:
        column = names.index(text)
        leaf = types[column]
        if not is_primitive(leaf):
            raise primitive_error(text, kind)
        return FieldPath(text, text, column, (), leaf)

    segments = parse_field_path(text)
    root = segments[0][1]
    if root not in names:
        raise UserError(
            "%s column not present in resolved schema: %s" % (kind, text), EXIT_SCHEMA
        )
    column = names.index(root)
    current = types[column]
    steps = []
    dynamic = False
    for position, segment in enumerate(segments[1:]):
        if dynamic:
            steps.append(("dyn", segment))
            continue
        kind_of = type_kind(current)
        if kind_of == "json":
            dynamic = True
            steps.append(("dyn", segment))
            continue
        if kind_of == "primitive":
            raise primitive_error(text, kind)
        if kind_of == "struct":
            if segment[0] == "index":
                raise primitive_error(text, kind)
            field_name = segment[1]
            found = None
            for name, field_type in current[1]:
                if name == field_name:
                    found = field_type
                    break
            if found is None:
                raise primitive_error(text, kind)
            steps.append(("field", field_name))
            current = found
        elif kind_of == "array":
            if segment[0] == "index":
                position_index = segment[1]
            elif segment[0] == "name" and INDEX_RE.match(segment[1]):
                position_index = int(segment[1])
            else:
                raise UserError(
                    'ERR 3 %s column "%s" uses a non-integer array index' % (kind, text),
                    EXIT_SCHEMA,
                )
            steps.append(("index", position_index))
            current = current[1]
        elif kind_of == "map":
            steps.append(("key", str(segment[1])))
            current = current[1]
        else:
            raise primitive_error(text, kind)

    leaf_type = None if dynamic else current
    if leaf_type is not None and not is_primitive(leaf_type):
        raise primitive_error(text, kind)
    return FieldPath(text, path_label(segments), column, tuple(steps), leaf_type)


def walk_path(value, steps):
    """Follow ``steps`` through a cast value tree; missing/out of range -> None."""
    for step in steps:
        if value is None:
            return None
        kind = step[0]
        if kind == "field" or kind == "key":
            if not isinstance(value, dict):
                return None
            value = value.get(step[1])
        elif kind == "index":
            if not isinstance(value, (list, tuple)):
                return None
            index = step[1]
            value = value[index] if 0 <= index < len(value) else None
        else:  # dynamic segment inside a free-form json value
            segment_kind, segment_value = step[1]
            if isinstance(value, dict):
                value = value.get(str(segment_value))
            elif isinstance(value, (list, tuple)):
                if segment_kind == "index":
                    index = segment_value
                elif segment_kind == "name" and INDEX_RE.match(segment_value):
                    index = int(segment_value)
                else:
                    return None
                value = value[index] if 0 <= index < len(value) else None
            else:
                return None
    return value


def leaf_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return value
    return typed_to_string(normalize_typed(value))


def leaf_sort_key(leaf_type, value):
    if leaf_type is not None and is_primitive(leaf_type):
        ok, _text, _json_value, key = cast_primitive(leaf_type, value, False)
        if ok:
            return key
    if isinstance(value, bool):
        return [1, 0, 1 if value else 0]
    if isinstance(value, (int, float)):
        return [1, 0, value]
    return [1, 1, leaf_text(value)]


def path_fragment(path, tree, kind):
    """Resolve one field path inside a cast tree: ``(text, sort_key)``."""
    leaf = walk_path(tree, path.steps)
    if leaf is None:
        return None, None
    if isinstance(leaf, (dict, list, tuple)):
        raise primitive_error(path.text, kind)
    return leaf_text(leaf), leaf_sort_key(path.leaf_type, leaf)


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


def typed_value_candidates(value):
    """Return ``(candidate_types, has_time)`` for one observed typed value."""
    value = normalize_typed(value)
    if isinstance(value, str):
        return value_candidates(value)
    if isinstance(value, bool):
        return {"bool", "string"}, False
    if isinstance(value, int):
        candidates = {"int", "float", "string"}
        if value in (0, 1):
            candidates.add("bool")
        return candidates, False
    if isinstance(value, float):
        candidates = {"float", "string"}
        if value in (0.0, 1.0):
            candidates.add("bool")
        return candidates, False
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return {"timestamp", "date", "string"}, False
        return {"timestamp", "string"}, True
    if isinstance(value, date_cls):
        return {"date", "timestamp", "string"}, False
    return {"string"}, False


def type_candidates(typ):
    """Which target types can losslessly hold every value of ``typ``."""
    if typ == "int":
        return {"int", "float", "string"}
    if typ == "float":
        return {"float", "string"}
    if typ == "bool":
        return {"bool", "string"}
    if typ == "date":
        return {"date", "timestamp", "string"}
    if typ == "timestamp":
        return {"timestamp", "string"}
    return {"string"}


def widen(left, right):
    """Simplest common type that can hold both ``left`` and ``right``."""
    if left == right:
        return left
    pair = {left, right}
    if pair == {"int", "float"}:
        return "float"
    if pair == {"date", "timestamp"}:
        return "timestamp"
    return "string"


class ColumnObserver:
    """Accumulates the intersection of candidate types over observed values."""

    __slots__ = ("candidates", "has_time", "observed", "declared")

    def __init__(self, declared=None):
        self.candidates = None  # None == nothing observed yet
        self.has_time = False
        self.observed = False
        self.declared = declared
        if declared is not None:
            self.observed = True
            self.candidates = set(type_candidates(declared))
            self.has_time = declared == "timestamp"

    def _merge(self, candidates, has_time):
        self.observed = True
        self.has_time = self.has_time or has_time
        if self.candidates is None:
            self.candidates = set(candidates)
        else:
            self.candidates &= candidates

    def observe(self, text):
        self._merge(*value_candidates(text))

    def observe_typed(self, value):
        self._merge(*typed_value_candidates(value))

    def resolve(self):
        if self.declared is not None:
            return self.declared
        if not self.observed or not self.candidates:
            return "string"
        best = min(self.candidates, key=lambda t: TYPE_PRIORITY[t])
        # Keep pure date columns as dates: only promote to timestamp when a
        # value actually carried a time component.
        if best == "timestamp" and not self.has_time and "date" in self.candidates:
            return "date"
        return best


# --------------------------------------------------------------------------
# Input format / compression detection
# --------------------------------------------------------------------------


class InputSource:
    """One resolved input: path plus the format and compression to use."""

    __slots__ = ("path", "fmt", "compression", "order", "raw", "rank")

    def __init__(self, path, fmt, compression, order):
        self.path = path
        self.fmt = fmt
        self.compression = compression
        self.order = order
        self.raw = fmt in RAW_FORMATS
        self.rank = FORMAT_RANK[fmt]


def read_head(path, size=8):
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc.strerror or exc))


def read_gzip_head(path, size=8):
    try:
        with gzip.open(path, "rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (path, exc.strerror or exc))
    except EOFError:
        return b""
    except Exception as exc:  # zlib/gzip decoding failures
        raise UserError(
            "%s: not a valid gzip stream: %s" % (path, exc), EXIT_MALFORMED
        )


def resolve_compression(path, head, forced):
    is_gzip = head[:2] == GZIP_MAGIC
    ext_gzip = path.lower().endswith(".gz")
    if forced == "none":
        if is_gzip:
            raise UserError(
                "%s: --compression=none but the file is gzip-compressed" % path,
                EXIT_MALFORMED,
            )
        return "none"
    if forced == "gzip":
        if not is_gzip:
            raise UserError(
                "%s: --compression=gzip but the file is not gzip-compressed" % path,
                EXIT_MALFORMED,
            )
        return "gzip"
    # auto
    if ext_gzip and not is_gzip:
        raise UserError(
            "%s: .gz suffix but the file is not gzip-compressed" % path, EXIT_MALFORMED
        )
    return "gzip" if is_gzip else "none"


def resolve_format(path, head, compression, forced):
    if forced != "auto":
        return forced
    lowered = path.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    _, ext = os.path.splitext(lowered)
    fmt = EXT_FORMAT.get(ext)
    if fmt is not None:
        return fmt
    magic = read_gzip_head(path) if compression == "gzip" else head
    if magic[:4] == PARQUET_MAGIC:
        return "parquet"
    raise UserError(
        "cannot determine input format for %s (use --input-format)" % path, EXIT_USAGE
    )


def resolve_inputs(paths, input_format, compression):
    sources = []
    for order, path in enumerate(paths):
        if not os.path.isfile(path):
            raise UserError("input file not found: %s" % path)
        head = read_head(path)
        comp = resolve_compression(path, head, compression)
        fmt = resolve_format(path, head, comp, input_format)
        sources.append(InputSource(path, fmt, comp, order))
    return sources


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


def open_text(source):
    try:
        if source.compression == "gzip":
            return gzip.open(source.path, "rt", encoding="utf-8-sig", newline="")
        return open(source.path, "r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (source.path, exc.strerror or exc))


DECODE_ERRORS = (EOFError, UnicodeDecodeError, zlib.error)


def stream_error(source, exc):
    """Translate a low-level streaming failure into a user-facing error."""
    if isinstance(exc, UnicodeDecodeError):
        return UserError(
            "%s: input is not valid UTF-8: %s" % (source.path, exc), EXIT_MALFORMED
        )
    if isinstance(exc, DECODE_ERRORS) or isinstance(exc, gzip.BadGzipFile):
        return UserError(
            "%s: corrupt or truncated %s stream: %s"
            % (source.path, "gzip" if source.compression == "gzip" else "input", exc),
            EXIT_MALFORMED,
        )
    return UserError(
        "cannot read input %s: %s" % (source.path, getattr(exc, "strerror", None) or exc)
    )


def delimited_dialect(source, options):
    if source.fmt == "tsv":
        return {
            "delimiter": "\t",
            "quotechar": '"',
            "quoting": csv.QUOTE_NONE,
            "escapechar": None,
            "doublequote": False,
        }
    return {
        "delimiter": ",",
        "quotechar": options["quotechar"],
        "escapechar": options["escapechar"],
        "doublequote": options["doublequote"],
    }


def iter_delimited(source, options):
    """Yield ``(header_tuple, values, line_number)`` for a CSV/TSV input."""
    handle = open_text(source)
    try:
        reader = csv.reader(handle, **delimited_dialect(source, options))
        try:
            header = next(reader, None)
        except csv.Error as exc:
            raise UserError(
                "%s:1: malformed %s input: %s" % (source.path, source.fmt.upper(), exc),
                EXIT_MALFORMED,
            )
        if header is None:
            return
        header = tuple(header)
        width = len(header)
        line_no = 1
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                raise UserError(
                    "%s:%d: malformed %s input: %s"
                    % (source.path, line_no + 1, source.fmt.upper(), exc),
                    EXIT_MALFORMED,
                )
            line_no += 1
            if not row:
                continue
            if source.fmt == "tsv" and len(row) > width:
                raise UserError(
                    "%s:%d: literal tab inside a TSV field (%d fields, header has %d)"
                    % (source.path, line_no, len(row), width),
                    EXIT_MALFORMED,
                )
            yield header, row, line_no
    except DECODE_ERRORS as exc:
        raise stream_error(source, exc)
    except OSError as exc:
        raise stream_error(source, exc)
    finally:
        handle.close()


NESTED_NEEDS_SCHEMA = "ERR 6 nested structure requires provided --schema"


def iter_jsonl(source, allow_nested=False):
    """Yield ``(keys_tuple, values, line_number)`` for a JSON Lines input."""
    handle = open_text(source)
    shapes = {}
    try:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise UserError(
                    "%s:%d: invalid JSON: %s" % (source.path, line_no, exc),
                    EXIT_MALFORMED,
                )
            if not isinstance(record, dict):
                raise UserError(
                    "%s:%d: JSONL record must be a flat JSON object" % (source.path, line_no),
                    EXIT_UNSUPPORTED,
                )
            keys = tuple(record)
            shape = shapes.get(keys)
            if shape is None:
                shape = keys
                if len(shapes) < 4096:
                    shapes[keys] = keys
            values = []
            for key in keys:
                value = record[key]
                if isinstance(value, (dict, list)):
                    if not allow_nested:
                        raise UserError(
                            "%s (file=%s line=%d field=%r)"
                            % (NESTED_NEEDS_SCHEMA, source.path, line_no, key),
                            EXIT_UNSUPPORTED,
                        )
                    values.append(value)
                else:
                    values.append(normalize_json_number(value))
            yield shape, values, line_no
    except DECODE_ERRORS as exc:
        raise stream_error(source, exc)
    except OSError as exc:
        raise stream_error(source, exc)
    finally:
        handle.close()


def load_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise UserError("reading Parquet inputs requires the 'pyarrow' package (%s)" % exc)
    return pa, pq


def arrow_type_name(pa, arrow_type):
    if pa.types.is_boolean(arrow_type):
        return "bool"
    if pa.types.is_integer(arrow_type):
        return "int"
    if pa.types.is_floating(arrow_type) or pa.types.is_decimal(arrow_type):
        return "float"
    if pa.types.is_date(arrow_type):
        return "date"
    if pa.types.is_timestamp(arrow_type):
        return "timestamp"
    return "string"


def materialize_parquet(source, temp_dir):
    """Parquet needs a seekable file; transparently decompress a .gz input."""
    if source.compression != "gzip":
        return source.path, None
    fd, path = tempfile.mkstemp(prefix="merge_parquet_", suffix=".parquet", dir=temp_dir)
    try:
        with os.fdopen(fd, "wb") as out, gzip.open(source.path, "rb") as src:
            shutil.copyfileobj(src, out, 1024 * 1024)
    except OSError as exc:
        raise UserError("cannot read input %s: %s" % (source.path, exc.strerror or exc))
    except Exception as exc:
        raise UserError("%s: not a valid gzip stream: %s" % (source.path, exc), EXIT_MALFORMED)
    return path, path


def open_parquet(source, temp_dir, allow_nested=False):
    """Open a Parquet file and return ``(pa, handle, names, types, scratch)``."""
    pa, pq = load_pyarrow()
    path, scratch = materialize_parquet(source, temp_dir)
    try:
        handle = pq.ParquetFile(path)
    except Exception as exc:
        if scratch:
            _unlink(scratch)
        raise UserError("%s: cannot read Parquet file: %s" % (source.path, exc), EXIT_MALFORMED)
    names, types = [], []
    try:
        for field in handle.schema_arrow:
            if pa.types.is_nested(field.type) and not allow_nested:
                raise UserError(
                    "%s (file=%s field=%r type=%s)"
                    % (NESTED_NEEDS_SCHEMA, source.path, field.name, field.type),
                    EXIT_UNSUPPORTED,
                )
            names.append(field.name)
            types.append(arrow_type_name(pa, field.type))
    except UserError:
        handle.close()
        if scratch:
            _unlink(scratch)
        raise
    return pa, handle, names, types, scratch


def parquet_batch_rows(handle, target_bytes):
    """Translate an advisory byte budget into a row-batch size."""
    try:
        meta = handle.metadata
        total_bytes = 0
        total_rows = 0
        for index in range(meta.num_row_groups):
            group = meta.row_group(index)
            total_bytes += group.total_byte_size
            total_rows += group.num_rows
    except Exception:
        total_bytes = total_rows = 0
    if total_rows <= 0 or total_bytes <= 0:
        return 4096
    average = max(1.0, float(total_bytes) / float(total_rows))
    rows = int(target_bytes / average)
    return max(64, min(rows, 131072))


def parquet_column_values(column):
    """Materialize one Arrow column, decoding map columns as dictionaries."""
    try:
        return column.to_pylist(maps_as_pydicts="lossy")
    except TypeError:
        return column.to_pylist()


def iter_parquet(source, temp_dir, target_bytes, allow_nested=False):
    """Yield ``(names_tuple, values, row_number)`` streaming row group-wise."""
    _pa, handle, names, _types, scratch = open_parquet(source, temp_dir, allow_nested)
    names_tuple = tuple(names)
    batch_rows = parquet_batch_rows(handle, target_bytes)
    row_no = 0
    try:
        if not names:
            return
        for batch in handle.iter_batches(batch_size=batch_rows):
            columns = [parquet_column_values(column) for column in batch.columns]
            for values in zip(*columns):
                row_no += 1
                yield names_tuple, list(values), row_no
    except UserError:
        raise
    except Exception as exc:
        raise UserError("%s: cannot read Parquet file: %s" % (source.path, exc), EXIT_MALFORMED)
    finally:
        try:
            handle.close()
        except Exception:
            pass
        if scratch:
            _unlink(scratch)


def iter_source(source, options):
    if source.fmt in RAW_FORMATS:
        return iter_delimited(source, options)
    if source.fmt == "jsonl":
        return iter_jsonl(source, options["allow_nested"])
    if source.fmt == "parquet":
        return iter_parquet(
            source,
            options["temp_dir"],
            options["parquet_bytes"],
            options["allow_nested"],
        )
    raise UserError("unsupported input format %r" % source.fmt)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------


def load_schema(spec, aliases):
    """Load the declared output schema, resolving aliases and nested types."""
    data = read_json_spec(spec, "schema", EXIT_SCHEMA, "schema file")

    columns = data.get("columns") if isinstance(data, dict) else data
    if not isinstance(columns, list) or not columns:
        raise UserError("schema must contain a non-empty 'columns' list", EXIT_SCHEMA)

    names, types = [], []
    for entry in columns:
        if isinstance(entry, str):
            name, spec_type = entry, "string"
        elif isinstance(entry, dict):
            lowered = lower_keys(entry)
            name = lowered.get("name")
            spec_type = lowered.get("type", "string")
        else:
            raise UserError("invalid schema column entry: %r" % (entry,), EXIT_SCHEMA)
        if not isinstance(name, str) or not name:
            raise UserError("schema column is missing a name", EXIT_SCHEMA)
        if name in names:
            raise UserError("duplicate column %r in schema" % name, EXIT_SCHEMA)
        names.append(name)
        types.append(parse_type_node(spec_type, aliases, 'column "%s"' % name))
    return names, types


class FileStats:
    """Per-input column observations used for schema reconciliation."""

    __slots__ = ("source", "observers")

    def __init__(self, source, observers):
        self.source = source
        self.observers = observers


def observe_source(source, options):
    """Collect one :class:`ColumnObserver` per column of a single input."""
    observers = {}
    mode = options["infer"]
    null_literal = options["null_literal"]
    loose = mode == "loose"

    if source.fmt == "parquet":
        _pa, handle, names, types, scratch = open_parquet(
            source, options["temp_dir"], options["allow_nested"]
        )
        try:
            for name, typ in zip(names, types):
                if name not in observers:
                    observers[name] = ColumnObserver(declared=typ)
        finally:
            try:
                handle.close()
            except Exception:
                pass
            if scratch:
                _unlink(scratch)
        return observers

    raw = source.raw
    cached_names = None
    slots = None
    for names, values, _line_no in iter_source(source, options):
        if names is not cached_names:
            cached_names = names
            slots = []
            seen = set()
            for position, name in enumerate(names):
                if name in seen:
                    continue
                seen.add(name)
                observer = observers.get(name)
                if observer is None:
                    observer = ColumnObserver()
                    observers[name] = observer
                slots.append((position, observer))
        width = len(values)
        for position, observer in slots:
            value = values[position] if position < width else ("" if raw else None)
            if raw:
                if null_literal != "" and value == null_literal:
                    continue
                if loose and value == "":
                    continue
                observer.observe(value)
            else:
                if value is None:
                    continue
                if isinstance(value, str):
                    if null_literal != "" and value == null_literal:
                        continue
                    if loose and value == "":
                        continue
                    observer.observe(value)
                else:
                    observer.observe_typed(value)
    return observers


def resolve_column_type(entries, strategy, mode):
    """Reconcile one column's type across the inputs that carry it."""
    entries = [entry for entry in entries if entry[1].observed]
    if not entries:
        return "string"

    if strategy == "authoritative":
        typed = [e for e in entries if e[0].fmt in TYPED_FORMATS]
        if typed:
            best = min(typed, key=lambda e: (e[0].rank, e[0].order))
            return best[1].resolve()
        if mode == "loose":
            pooled = ColumnObserver()
            for _source, observer in entries:
                pooled._merge(observer.candidates or {"string"}, observer.has_time)
            return pooled.resolve()
        resolved = None
        for _source, observer in entries:
            candidate = observer.resolve()
            if resolved is None:
                resolved = candidate
            elif resolved != candidate:
                return "string"
        return resolved or "string"

    if strategy == "consensus":
        votes = {}
        for _source, observer in entries:
            typ = observer.resolve()
            votes[typ] = votes.get(typ, 0) + 1
        top = max(votes.values())
        tied = sorted((t for t, n in votes.items() if n == top), key=lambda t: TYPE_PRIORITY[t])
        resolved = tied[0]
        for typ in tied[1:]:
            resolved = widen(resolved, typ)
        return resolved

    # union: simplest common type that can hold every observed value.
    candidates = None
    has_time = False
    for _source, observer in entries:
        observed = observer.candidates or {"string"}
        has_time = has_time or observer.has_time
        candidates = set(observed) if candidates is None else (candidates & observed)
    if not candidates:
        return "string"
    best = min(candidates, key=lambda t: TYPE_PRIORITY[t])
    if best == "timestamp" and not has_time and "date" in candidates:
        return "date"
    return best


def infer_schema(sources, options):
    """Infer the output columns (lexicographic) and their reconciled types."""
    per_column = {}
    for source in sources:
        observers = observe_source(source, options)
        for name, observer in observers.items():
            per_column.setdefault(name, []).append((source, observer))

    names = sorted(per_column)
    strategy = options["strategy"]
    mode = options["infer"]
    types = [resolve_column_type(per_column[name], strategy, mode) for name in names]
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
        fd, path = tempfile.mkstemp(prefix="merge_run_", suffix=".jsonl", dir=self.temp_dir)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
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
            _unlink(path)
        self.runs = []
        self.buffer = []


def read_run(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for line in handle:
            if line:
                yield json.loads(line)


# --------------------------------------------------------------------------
# Partitioning
# --------------------------------------------------------------------------

# Characters that survive a Hive-style path segment untouched.
PARTITION_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)

NULL_PARTITION = "_null"

PART_PREFIX = "part-"
PART_SUFFIX = ".csv"
PART_WIDTH = 5


def encode_partition_value(text):
    """Percent-encode the UTF-8 bytes of ``text`` for use in a path segment.

    Every byte outside ``[A-Za-z0-9._-]`` becomes ``%XX`` (upper-case hex), so
    a space renders as ``%20`` and ``/`` as ``%2F``.
    """
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if char in PARTITION_SAFE:
            out.append(char)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def partition_segments(labels, values):
    """Build the ``<col>=<val>`` path segments for one output row."""
    segments = []
    for label, value in zip(labels, values):
        encoded = NULL_PARTITION if value is None else encode_partition_value(value)
        segments.append(label + "=" + encoded)
    return segments


def part_name(index):
    return "%s%0*d%s" % (PART_PREFIX, PART_WIDTH, index, PART_SUFFIX)


# --------------------------------------------------------------------------
# Output writers
# --------------------------------------------------------------------------


def output_dialect(options):
    return {
        "delimiter": ",",
        "quotechar": options["quotechar"],
        "escapechar": options["escapechar"],
        "doublequote": options["doublequote"],
        "lineterminator": "\n",
        "quoting": csv.QUOTE_MINIMAL,
    }


class RowFormatter:
    """Renders a row exactly as it is written, so byte counts stay exact."""

    def __init__(self, dialect):
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer, **dialect)

    def format(self, values):
        self._buffer.seek(0)
        self._buffer.truncate(0)
        self._writer.writerow(values)
        return self._buffer.getvalue()


class ShardWriter:
    """Writes ``part-00000.csv``, ``part-00001.csv``, ... into one directory.

    A new shard is started as soon as appending the next row would break the
    row-count or byte-size limit; a row that cannot fit even on its own is
    written anyway, alone in its shard.
    """

    def __init__(self, directory, header_text, max_rows, max_bytes):
        self.directory = directory
        self.header_text = header_text
        self.header_bytes = len(header_text.encode("utf-8"))
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.index = 0
        self.handle = None
        self.rows = 0
        self.size = 0

    def _open(self):
        path = os.path.join(self.directory, part_name(self.index))
        try:
            self.handle = open(path, "w", encoding="utf-8", newline="")
            self.handle.write(self.header_text)
        except OSError as exc:
            raise UserError("cannot write output %s: %s" % (path, exc.strerror or exc))
        self.index += 1
        self.rows = 0
        self.size = self.header_bytes

    def _cut_before(self, nbytes):
        if self.rows == 0:
            return False
        if self.max_rows is not None and self.rows + 1 > self.max_rows:
            return True
        if self.max_bytes is not None and self.size + nbytes > self.max_bytes:
            return True
        return False

    def start(self):
        """Materialize the first (possibly row-less) shard."""
        if self.handle is None and self.index == 0:
            self._open()

    def write(self, text, nbytes):
        if self.handle is None:
            self._open()
        elif self._cut_before(nbytes):
            self.close()
            self._open()
        try:
            self.handle.write(text)
        except OSError as exc:
            raise UserError("cannot write output: %s" % (exc.strerror or exc))
        self.rows += 1
        self.size += nbytes

    def close(self):
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        try:
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()


def write_single(destination, names, records, null_literal, options):
    """Write the whole sorted stream as one CSV file (or to stdout)."""
    dialect = output_dialect(options)

    def emit(handle):
        out = csv.writer(handle, **dialect)
        out.writerow(names)
        for record in records:
            out.writerow([null_literal if v is None else v for v in record[3]])
        handle.flush()

    if destination == "-":
        handle = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="", closefd=False)
        try:
            emit(handle)
        finally:
            try:
                handle.flush()
            except Exception:
                pass
        return

    target = os.path.abspath(destination)
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise UserError("cannot create output directory: %s" % (exc.strerror or exc))
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".merge_files_", suffix=".tmp", dir=parent or ".")
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            emit(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        _unlink(tmp_path)
        raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))
    except BaseException:
        _unlink(tmp_path)
        raise


def promote_directory(staging, target, destination):
    """Move the fully written staging directory onto ``target`` atomically."""
    parent = os.path.dirname(target) or "."
    try:
        if os.path.isdir(target):
            holder = tempfile.mkdtemp(prefix=".merge_files_old_", dir=parent)
            os.rmdir(holder)
            os.rename(target, holder)
            try:
                os.rename(staging, target)
            except OSError:
                os.rename(holder, target)
                raise
            shutil.rmtree(holder, ignore_errors=True)
        else:
            os.rename(staging, target)
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))


def write_partitioned(
    destination, names, records, by_fields, max_rows, max_bytes, null_literal, options
):
    """Write the sorted stream as a directory tree of CSV shards.

    Records arrive grouped by partition (the partition segments lead the sort
    key), so one shard writer at a time is enough however many partitions the
    data has.
    """
    if destination == "-":
        raise UserError("--output must be a directory path (not -) when partitioning")

    target = os.path.abspath(destination)
    if os.path.exists(target) and not os.path.isdir(target):
        raise UserError("--output %s exists and is not a directory" % destination)
    parent = os.path.dirname(target) or "."
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise UserError("cannot create output directory: %s" % (exc.strerror or exc))
    try:
        staging = tempfile.mkdtemp(prefix=".merge_files_out_", dir=parent)
    except OSError as exc:
        raise UserError("cannot write output %s: %s" % (destination, exc.strerror or exc))

    formatter = RowFormatter(output_dialect(options))
    header_text = formatter.format(names)

    writer = None
    try:
        current = None
        for record in records:
            segments = record[0]
            if writer is None or segments != current:
                if writer is not None:
                    writer.close()
                current = segments
                directory = os.path.join(staging, *segments) if segments else staging
                try:
                    os.makedirs(directory, exist_ok=True)
                except OSError as exc:
                    raise UserError(
                        "cannot create partition directory %s: %s"
                        % (os.path.join(*segments), exc.strerror or exc)
                    )
                writer = ShardWriter(directory, header_text, max_rows, max_bytes)
            text = formatter.format([null_literal if v is None else v for v in record[3]])
            writer.write(text, len(text.encode("utf-8")))

        if writer is None and not by_fields:
            # No rows at all: still emit one header-only shard.
            writer = ShardWriter(staging, header_text, max_rows, max_bytes)
            writer.start()
        if writer is not None:
            writer.close()
        promote_directory(staging, target, destination)
    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        raise


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
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument(
        "--key",
        required=True,
        action="append",
        help="sort key column(s); comma-separated, may be repeated",
    )
    parser.add_argument("--desc", action="store_true", help="sort all keys descending")
    parser.add_argument(
        "--partition-by",
        action="append",
        metavar="COLS",
        help="Hive-style partition column(s); comma-separated, may be repeated",
    )
    parser.add_argument(
        "--max-rows-per-file",
        type=int,
        default=None,
        metavar="INT",
        help="cut each output file after this many data rows",
    )
    parser.add_argument(
        "--max-bytes-per-file",
        type=int,
        default=None,
        metavar="INT",
        help="cut each output file so its on-disk size stays within this many bytes",
    )
    parser.add_argument("--schema", help="schema JSON file (or inline JSON)")
    parser.add_argument(
        "--type-alias-file",
        metavar="ALIASES_JSON",
        help="JSON file of additional type aliases (or inline JSON)",
    )
    parser.add_argument("--infer", choices=("strict", "loose"), default="strict")
    parser.add_argument(
        "--schema-strategy",
        choices=("authoritative", "consensus", "union"),
        default="authoritative",
    )
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
    parser.add_argument(
        "--input-format",
        choices=("auto", "csv", "tsv", "jsonl", "parquet"),
        default="auto",
    )
    parser.add_argument("--compression", choices=("auto", "none", "gzip"), default="auto")
    parser.add_argument(
        "--parquet-row-group-bytes",
        type=int,
        default=0,
        help="advisory batch size in bytes when streaming Parquet row groups",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def run(args):
    if args.memory_limit_mb is not None and args.memory_limit_mb <= 0:
        raise UserError("--memory-limit-mb must be a positive integer")
    if args.parquet_row_group_bytes is not None and args.parquet_row_group_bytes < 0:
        raise UserError("--parquet-row-group-bytes must be a non-negative integer")

    keys = []
    for chunk in args.key:
        for name in split_paths(chunk):
            name = name.strip()
            if name and name not in keys:
                keys.append(name)
    if not keys:
        raise UserError("--key requires at least one column name")

    partition_cols = []
    for chunk in args.partition_by or []:
        for name in split_paths(chunk):
            name = name.strip()
            if name and name not in partition_cols:
                partition_cols.append(name)
    if args.partition_by is not None and not partition_cols:
        raise UserError("--partition-by requires at least one column name")

    max_rows = args.max_rows_per_file
    max_bytes = args.max_bytes_per_file
    if max_rows is not None and max_rows <= 0:
        raise UserError("--max-rows-per-file must be a positive integer")
    if max_bytes is not None and max_bytes <= 0:
        raise UserError("--max-bytes-per-file must be a positive integer")

    partitioned = bool(partition_cols) or max_rows is not None or max_bytes is not None
    if partitioned and args.output == "-":
        raise UserError("--output must be a directory path (not -) when partitioning")

    sources = resolve_inputs(args.inputs, args.input_format, args.compression)

    memory_bytes = args.memory_limit_mb * 1024 * 1024
    parquet_bytes = args.parquet_row_group_bytes or max(1024 * 1024, memory_bytes // 8)

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

    options = {
        "quotechar": args.csv_quotechar,
        "escapechar": args.csv_escapechar,
        "doublequote": args.csv_escapechar is None,
        "null_literal": args.csv_null_literal,
        "infer": args.infer,
        "strategy": args.schema_strategy,
        "temp_dir": temp_dir,
        "parquet_bytes": parquet_bytes,
        # Nested inputs are only accepted when a schema declares their shape.
        "allow_nested": bool(args.schema),
    }
    null_literal = args.csv_null_literal

    writer = None
    try:
        aliases = load_aliases(args.type_alias_file)
        if args.schema:
            names, types = load_schema(args.schema, aliases)
        else:
            names, types = infer_schema(sources, options)

        if not names:
            raise UserError("no columns found in the inputs", EXIT_SCHEMA)

        missing = [k for k in keys if k not in names and path_root(k) not in names]
        if missing:
            raise UserError(
                "key column%s not present in resolved schema: %s"
                % ("" if len(missing) == 1 else "s", ", ".join(missing)),
                EXIT_SCHEMA,
            )

        missing = [
            c for c in partition_cols if c not in names and path_root(c) not in names
        ]
        if missing:
            raise UserError(
                "partition column%s not present in resolved schema: %s"
                % ("" if len(missing) == 1 else "s", ", ".join(missing)),
                EXIT_SCHEMA,
            )

        key_paths = [resolve_field_path(k, names, types, "key") for k in keys]
        partition_paths = [
            resolve_field_path(c, names, types, "partition") for c in partition_cols
        ]
        partition_labels = [path.label for path in partition_paths]
        # Columns whose cast value/sort key a key or partition path needs.
        needed = set(path.column for path in key_paths)
        needed.update(path.column for path in partition_paths)
        on_type_error = args.on_type_error
        reverse = bool(args.desc)
        cast_ctx = CastContext(on_type_error, null_literal)

        # Serialized records cost far less than the equivalent live Python
        # objects, so only part of the budget is handed to the sort buffer.
        writer = RunWriter(temp_dir, int(memory_bytes * 0.25), reverse)

        sequence = 0
        for source in sources:
            raw = source.raw
            cached_names = None
            projection = None
            cast_ctx.file = source.path
            for row_names, values, line_no in iter_source(source, options):
                if row_names is not cached_names:
                    cached_names = row_names
                    index = {}
                    for position, name in enumerate(row_names):
                        if name not in index:
                            index[name] = position
                    projection = [index.get(name) for name in names]

                cast_ctx.line = line_no
                width = len(values)
                out_values = []
                # For a primitive column this holds its sort key; for a nested
                # one, the cast value tree that field paths are resolved in.
                aux = [None] * len(types)
                for column_position, typ in enumerate(types):
                    position = projection[column_position]
                    if position is None or position >= width:
                        out_values.append(None)
                        continue
                    cell = values[position]
                    name = names[column_position]
                    primitive = is_primitive(typ)

                    if raw:
                        if is_null_text(cell, null_literal):
                            out_values.append(None)
                            continue
                        if not primitive:
                            out, tree = cast_nested_cell(typ, cell, True, name, cast_ctx)
                            out_values.append(out)
                            if column_position in needed:
                                aux[column_position] = tree
                            continue
                        ok, out, cell_key = cast_cell(typ, cell)
                        original = cell
                    else:
                        if cell is None or (
                            null_literal != ""
                            and isinstance(cell, str)
                            and cell == null_literal
                        ):
                            out_values.append(None)
                            continue
                        if not primitive:
                            out, tree = cast_nested_cell(typ, cell, False, name, cast_ctx)
                            out_values.append(out)
                            if column_position in needed:
                                aux[column_position] = tree
                            continue
                        ok, out, cell_key = cast_value(typ, cell)
                        original = stringify_original(cell)

                    if not ok:
                        if on_type_error == "fail":
                            raise UserError(
                                "%s:%d: cannot cast %r to %s for column %r"
                                % (source.path, line_no, original, typ, name),
                                EXIT_TYPE,
                            )
                        if on_type_error == "keep-string":
                            out, cell_key = original, [1, 1, original]
                        else:  # coerce-null
                            out, cell_key = None, None
                    out_values.append(out)
                    if column_position in needed:
                        aux[column_position] = cell_key

                # Key order follows --key; nulls sort before non-nulls in
                # either direction (so they land last when reversed).
                ordered_key = []
                for path in key_paths:
                    if path.steps:
                        _text, fragment = path_fragment(
                            path, aux[path.column], "key"
                        )
                    else:
                        fragment = aux[path.column]
                    ordered_key.append(fragment or [0])

                # Partition segments lead the sort key so every partition's
                # rows arrive contiguously, already ordered by --key.
                if partition_paths:
                    part_values = []
                    for path in partition_paths:
                        if path.steps:
                            text, _fragment = path_fragment(
                                path, aux[path.column], "partition"
                            )
                        else:
                            text = out_values[path.column]
                        part_values.append(text)
                    segments = partition_segments(partition_labels, part_values)
                else:
                    segments = []

                sequence += 1
                tiebreak = -sequence if reverse else sequence
                record = [segments, ordered_key, tiebreak, out_values]
                approx = 96 + sum(len(v) + 48 for v in out_values if v is not None)
                writer.add(record, approx)

        if partitioned:
            write_partitioned(
                args.output,
                names,
                writer.sorted_records(),
                bool(partition_cols),
                max_rows,
                max_bytes,
                null_literal,
                options,
            )
        else:
            write_single(args.output, names, writer.sorted_records(), null_literal, options)
    finally:
        if writer is not None:
            writer.cleanup()
        if owns_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return EXIT_OK


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except UserError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return exc.code
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:
            pass
        return EXIT_OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

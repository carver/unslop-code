#!/usr/bin/env python3
"""Merge heterogeneous inputs (CSV, TSV, JSON Lines, Parquet) into one
schema-aligned, globally sorted CSV -- or, when a partitioning flag is given,
into a directory of Hive-partitioned and/or size-capped CSV parts.

A provided --schema may declare nested columns (struct, array<T>, map<string,T>,
json); nested columns are written as canonical JSON, and --key/--partition-by
accept dotted/bracketed field paths into them.

See AMBIGUITIES.md for the readings chosen where the spec allows more than one.
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
import pickle
import re
import shutil
import sys
import tempfile
from collections import OrderedDict
from datetime import date as _date
from datetime import datetime, time as _time, timedelta, timezone

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
STRING_ONLY = TYPE_BIT[STRING]

# Bit sets contributed by an already-typed value (JSONL / Parquet). See T23.
INT_BITS = TYPE_BIT[INT] | TYPE_BIT[FLOAT] | TYPE_BIT[STRING]
FLOAT_BITS = TYPE_BIT[FLOAT] | TYPE_BIT[STRING]
BOOL_BITS = TYPE_BIT[BOOL] | TYPE_BIT[STRING]
DATE_BITS = TYPE_BIT[DATE] | TYPE_BIT[STRING]
TS_BITS = TYPE_BIT[TIMESTAMP] | TYPE_BIT[STRING]

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

# Input formats.
CSV = "csv"
TSV = "tsv"
JSONL = "jsonl"
PARQUET = "parquet"

EXT_FORMAT = {
    ".csv": CSV,
    ".tsv": TSV,
    ".jsonl": JSONL,
    ".ndjson": JSONL,
    ".parquet": PARQUET,
}

# Precedence tiers for --schema-strategy=authoritative (lower wins). Parquet is
# the only source whose types travel with the file; JSONL ranks with CSV (T19).
FORMAT_RANK = {PARQUET: 0, JSONL: 1, CSV: 1, TSV: 1}

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

INT64_MAX = 2 ** 63 - 1

# Exit codes (T18).
EXIT_IO = 1
EXIT_FORMAT = 2
EXIT_SCHEMA = 3
EXIT_CAST = 4
EXIT_DIALECT = 5
EXIT_NESTED = 6


class ToolError(Exception):
    """A user-facing error: reported on stderr, exits with `code`."""

    def __init__(self, message, code=EXIT_IO):
        Exception.__init__(self, message)
        self.code = code


class CastError(Exception):
    pass


class _Null:
    """Sentinel for a missing/null cell."""

    __slots__ = ()

    def __repr__(self):
        return "NULL"


NULL = _Null()


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


def timestamp_from_datetime(value):
    """Normalize a datetime (naive = UTC) into a Timestamp."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    frac = "" if value.microsecond == 0 else "%06d" % value.microsecond
    return Timestamp(value, frac)


def typed_text(value):
    """Canonical text for an already-typed value; the single cast path (T33)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Timestamp):
        return value.text()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (_date, _time)):
        return value.isoformat()
    return str(value)


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
# Nested types: model, aliases, casting, canonical JSON, field paths
# --------------------------------------------------------------------------


class StructType:
    """An ordered record of named fields (names unique)."""

    kind = "struct"
    __slots__ = ("fields", "index")

    def __init__(self, fields):
        self.fields = fields
        self.index = dict(fields)


class ArrayType:
    kind = "array"
    __slots__ = ("element",)

    def __init__(self, element):
        self.element = element


class MapType:
    """map<string, T>: JSON object keys are strings by construction."""

    kind = "map"
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class JsonType:
    """The `json` (bare `struct`) type: any JSON value, normalized only."""

    kind = "json"
    __slots__ = ()


JSON_ANY = JsonType()


def is_primitive(type_obj):
    return isinstance(type_obj, str)


def type_label(type_obj):
    if is_primitive(type_obj):
        return type_obj
    kind = type_obj.kind
    if kind == "array":
        return "array<%s>" % type_label(type_obj.element)
    if kind == "map":
        return "map<string,%s>" % type_label(type_obj.value)
    if kind == "json":
        return "json"
    return "struct<%s>" % ",".join(
        "%s:%s" % (name, type_label(sub)) for name, sub in type_obj.fields
    )


# Always-present aliases (T55: the user's file may shadow any of them).
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

MAX_TYPE_DEPTH = 32


def split_generic(text):
    """`array<int>` -> ('array', 'int'); `int` -> ('int', None)."""
    pos = text.find("<")
    if pos < 0 or not text.endswith(">"):
        return text, None
    return text[:pos].strip(), text[pos + 1:-1]


def split_type_args(text):
    """Split `string,map<string,int>` at top-level commas."""
    parts = []
    depth = 0
    start = 0
    for pos, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:pos])
            start = pos + 1
    parts.append(text[start:])
    return [part.strip() for part in parts]


def alias_step(text, aliases):
    """One alias substitution for `text`, or None when it is not an alias."""
    if text in aliases:
        return aliases[text].strip().lower()
    head, args = split_generic(text)
    if args is not None and head in aliases:
        return aliases[head].strip().lower() + "<" + args + ">"
    return None


def resolve_alias_chain(text, aliases):
    """Follow aliases until a non-alias name is reached (cycles -> error 2)."""
    current = text.strip().lower()
    seen = set()
    while True:
        if current in seen:
            raise ToolError(
                "type alias cycle involving %r" % current, EXIT_FORMAT
            )
        seen.add(current)
        nxt = alias_step(current, aliases)
        if nxt is None:
            return current
        current = nxt


def parse_alias_document(document, origin):
    if not isinstance(document, dict):
        raise ToolError(
            "type alias file %s must be a JSON object" % origin, EXIT_SCHEMA
        )
    table = document.get("aliases", document)
    if not isinstance(table, dict):
        raise ToolError(
            "type alias file %s must hold an 'aliases' object" % origin, EXIT_SCHEMA
        )
    aliases = {}
    for name, target in table.items():
        if not isinstance(name, str) or not isinstance(target, str):
            raise ToolError(
                "type alias entries must map a name to a type name: %r -> %r"
                % (name, target),
                EXIT_SCHEMA,
            )
        aliases[name.strip().lower()] = target.strip().lower()
    return aliases


def load_aliases(source):
    """Built-ins plus the optional --type-alias-file, cycle-checked up front."""
    aliases = dict(BUILTIN_ALIASES)
    if source:
        aliases.update(parse_alias_document(*load_json_document(source, "alias")))
    for name in list(aliases):
        resolve_alias_chain(name, aliases)
    return aliases


def parse_type(node, aliases, where, depth=0):
    """Build a type object from a schema `type` value."""
    if depth > MAX_TYPE_DEPTH:
        raise ToolError(
            "type for %s nests deeper than %d levels (alias cycle?)"
            % (where, MAX_TYPE_DEPTH),
            EXIT_FORMAT,
        )
    if isinstance(node, dict):
        return parse_type_object(node, aliases, where, depth)
    if not isinstance(node, str):
        raise ToolError(
            "invalid type %r for %s" % (node, where), EXIT_SCHEMA
        )
    text = resolve_alias_chain(node, aliases)
    head, args = split_generic(text)
    if args is None:
        if head in VALID_TYPES:
            return head
        if head == "struct":
            # `json` resolves here: a struct with no declared fields (T48).
            return JSON_ANY
        raise ToolError(
            "invalid type %r for %s (valid: %s, struct, array<T>, map<string,T>, json)"
            % (node, where, ", ".join(VALID_TYPES)),
            EXIT_SCHEMA,
        )
    parts = split_type_args(args)
    if head == "array" and len(parts) == 1:
        return ArrayType(parse_type(parts[0], aliases, where, depth + 1))
    if head == "map" and len(parts) == 2:
        key_type = parse_type(parts[0], aliases, where, depth + 1)
        if key_type != STRING:
            raise ToolError(
                "map key type must be string for %s (got %r)" % (where, parts[0]),
                EXIT_SCHEMA,
            )
        return MapType(parse_type(parts[1], aliases, where, depth + 1))
    raise ToolError("invalid type %r for %s" % (node, where), EXIT_SCHEMA)


def parse_type_object(node, aliases, where, depth):
    entries = [(str(key).strip().lower(), value) for key, value in node.items()]
    if len(entries) != 1:
        raise ToolError(
            "nested type for %s must have exactly one of struct/array/map" % where,
            EXIT_SCHEMA,
        )
    kind, body = entries[0]
    if kind == "struct":
        fields = body.get("fields") if isinstance(body, dict) else body
        if not isinstance(fields, list):
            raise ToolError(
                "struct type for %s needs a 'fields' list" % where, EXIT_SCHEMA
            )
        built = []
        seen = set()
        for field in fields:
            if not isinstance(field, dict) or "name" not in field:
                raise ToolError(
                    "struct field entries for %s need a 'name': %r" % (where, field),
                    EXIT_SCHEMA,
                )
            name = field["name"]
            if name in seen:
                raise ToolError(
                    "duplicate struct field %r in %s" % (name, where), EXIT_SCHEMA
                )
            seen.add(name)
            built.append(
                (
                    name,
                    parse_type(
                        field.get("type", STRING),
                        aliases,
                        '%s field "%s"' % (where, name),
                        depth + 1,
                    ),
                )
            )
        return StructType(built)
    if kind == "array":
        element = body.get("element", body) if isinstance(body, dict) else body
        if element is None:
            raise ToolError(
                "array type for %s needs an 'element' type" % where, EXIT_SCHEMA
            )
        return ArrayType(parse_type(element, aliases, where, depth + 1))
    if kind == "map":
        if not isinstance(body, dict) or "value" not in body:
            raise ToolError(
                "map type for %s needs a 'value' type" % where, EXIT_SCHEMA
            )
        key_type = parse_type(body.get("key", STRING), aliases, where, depth + 1)
        if key_type != STRING:
            raise ToolError(
                "map key type must be string for %s" % where, EXIT_SCHEMA
            )
        return MapType(parse_type(body["value"], aliases, where, depth + 1))
    raise ToolError(
        "unknown nested type %r for %s" % (kind, where), EXIT_SCHEMA
    )


# --------------------------------------------------------------------------
# Nested casting
# --------------------------------------------------------------------------


def cast_error(text, type_obj, field, path, line):
    return ToolError(
        'cannot cast "%s" to %s in field "%s" (file=%s line=%s)'
        % (text, type_label(type_obj), field, path, line),
        EXIT_CAST,
    )


class KeptString(str):
    """Text substituted for a value that failed to cast under keep-string."""

    __slots__ = ()


def json_text_of(value):
    """Minified JSON for a raw (uncast) value -- the `keep-string` form (T52)."""
    if isinstance(value, (dict, list)):
        return canonical_json(normalize_json(value))
    return typed_text(value)


def handle_cast_failure(value, type_obj, field, policy, origin):
    text = json_text_of(value)
    if policy == "fail":
        raise cast_error(text, type_obj, field, origin[0], origin[1])
    if policy == "keep-string":
        return KeptString(text)
    return None


def normalize_json(value):
    """A `json`-typed value: no casting, objects sorted by key (T46)."""
    if isinstance(value, dict):
        items = [
            (key if isinstance(key, str) else typed_text(key), sub)
            for key, sub in value.items()
        ]
        items.sort(key=lambda item: item[0])
        return OrderedDict((key, normalize_json(sub)) for key, sub in items)
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if value is NULL:
        return None
    return value


def cast_nested(value, type_obj, field, policy, origin):
    """Cast `value` to `type_obj`, recursively; returns None for JSON null."""
    if value is NULL or value is None:
        return None
    if is_primitive(type_obj):
        if isinstance(value, (dict, list)):
            return handle_cast_failure(value, type_obj, field, policy, origin)
        if type_obj == INT and isinstance(value, float):
            # An integral JSON/Parquet float is an int for this purpose (T24).
            if (
                math.isfinite(value)
                and value.is_integer()
                and abs(value) <= INT64_MAX
            ):
                return int(value)
        text = value if isinstance(value, str) else typed_text(value)
        if type_obj == STRING:
            return text
        try:
            return CASTERS[type_obj](text)
        except CastError:
            return handle_cast_failure(value, type_obj, field, policy, origin)
    kind = type_obj.kind
    if kind == "json":
        return normalize_json(value)
    if kind == "struct":
        if not isinstance(value, dict):
            return handle_cast_failure(value, type_obj, field, policy, origin)
        out = OrderedDict()
        for name, sub in type_obj.fields:
            out[name] = cast_nested(
                value.get(name, None), sub, "%s.%s" % (field, name), policy, origin
            )
        return out
    if kind == "array":
        if not isinstance(value, list):
            return handle_cast_failure(value, type_obj, field, policy, origin)
        return [
            cast_nested(
                item, type_obj.element, "%s.%d" % (field, pos), policy, origin
            )
            for pos, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        return handle_cast_failure(value, type_obj, field, policy, origin)
    items = [
        (key if isinstance(key, str) else typed_text(key), sub)
        for key, sub in value.items()
    ]
    items.sort(key=lambda item: item[0])
    out = OrderedDict()
    for key, sub in items:
        out[key] = cast_nested(
            sub, type_obj.value, '%s["%s"]' % (field, key), policy, origin
        )
    return out


# --------------------------------------------------------------------------
# Canonical JSON output
# --------------------------------------------------------------------------


def json_quote(text):
    # RFC 8259 escaping only; non-ASCII stays UTF-8 (T47).
    return json.dumps(text, ensure_ascii=False)


def encode_json(value, out):
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(json_quote(value))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(json.dumps(value))
    elif isinstance(value, Timestamp):
        out.append(json_quote(value.text()))
    elif isinstance(value, dict):
        out.append("{")
        first = True
        for key, sub in value.items():
            if not first:
                out.append(",")
            first = False
            out.append(json_quote(key))
            out.append(":")
            encode_json(sub, out)
        out.append("}")
    elif isinstance(value, list):
        out.append("[")
        for pos, item in enumerate(value):
            if pos:
                out.append(",")
            encode_json(item, out)
        out.append("]")
    else:
        out.append(json_quote(typed_text(value)))


def canonical_json(value):
    out = []
    encode_json(value, out)
    return "".join(out)


# --------------------------------------------------------------------------
# Field paths (--key / --partition-by)
# --------------------------------------------------------------------------

NAME_STEP = 0
INDEX_STEP = 1
KEY_STEP = 2


def path_error(text, label, detail=None):
    if detail:
        return ToolError(
            '%s column "%s" %s' % (label, text, detail), EXIT_SCHEMA
        )
    return ToolError(
        '%s column "%s" does not resolve to a primitive' % (label, text),
        EXIT_SCHEMA,
    )


def parse_field_path(text, label):
    """`items.0.sku` / `attrs["country"]` -> (root name, [steps])."""
    size = len(text)
    pos = 0
    while pos < size and text[pos] not in ".[":
        pos += 1
    root = text[:pos]
    if not root:
        raise path_error(text, label, "is not a valid field path")
    steps = []
    while pos < size:
        char = text[pos]
        if char == ".":
            pos += 1
            start = pos
            while pos < size and text[pos] not in ".[":
                pos += 1
            token = text[start:pos]
            if not token:
                raise path_error(text, label, "is not a valid field path")
            steps.append((NAME_STEP, token))
            continue
        pos += 1
        if pos < size and text[pos] == '"':
            end = pos + 1
            while end < size and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if end >= size or end + 1 >= size or text[end + 1] != "]":
                raise path_error(text, label, "has an unterminated map lookup")
            try:
                key = json.loads(text[pos:end + 1])
            except ValueError:
                raise path_error(text, label, "has an invalid map key")
            steps.append((KEY_STEP, key))
            pos = end + 2
            continue
        end = text.find("]", pos)
        if end < 0:
            raise path_error(text, label, "has an unterminated bracket")
        token = text[pos:end]
        if token.isdigit():
            steps.append((INDEX_STEP, int(token)))
        else:
            raise path_error(
                text, label, "uses an unquoted map key (quotes are required)"
            )
        pos = end + 1
    return root, steps


class FieldPath:
    """A resolved --key/--partition-by path: where to look, and what it yields."""

    __slots__ = ("text", "column", "position", "steps", "leaf_type")

    def __init__(self, text, column, position, steps, leaf_type):
        self.text = text
        self.column = column
        self.position = position
        self.steps = steps
        self.leaf_type = leaf_type


def step_index(step):
    """The array index a step names, or None."""
    kind, token = step
    if kind == INDEX_STEP:
        return token
    if token.isdigit():
        return int(token)
    return None


def step_key(step):
    kind, token = step
    return str(token) if kind == INDEX_STEP else token


def walk_type(current, step, text, label):
    """Type reached by applying `step`; None means dynamic (inside `json`)."""
    if current is None:
        return None
    if is_primitive(current):
        raise path_error(text, label)
    kind = current.kind
    if kind == "json":
        return None
    if kind == "struct":
        if step[0] == INDEX_STEP:
            raise path_error(text, label)
        name = step[1]
        if name not in current.index:
            raise path_error(
                text, label, 'names field "%s", which the struct does not declare'
                % name
            )
        return current.index[name]
    if kind == "array":
        if step_index(step) is None:
            raise path_error(
                text, label, "uses a non-integer array index (indices must be "
                "non-negative integers)"
            )
        return current.element
    return current.value


def resolve_field_path(text, columns, types, label):
    """Static resolution of one path against the resolved schema."""
    text = text.strip()
    if text in types:
        root, steps = text, []
    else:
        root, steps = parse_field_path(text, label)
        if root not in types:
            raise ToolError(
                "%s column(s) not present in resolved schema: %s" % (label, text),
                EXIT_SCHEMA,
            )
    current = types[root]
    for step in steps:
        current = walk_type(current, step, text, label)
    if current is not None and not is_primitive(current):
        raise path_error(text, label)
    return FieldPath(text, root, columns.index(root), steps, current)


def navigate(value, steps):
    """Walk a cast value; missing/out-of-range/null yields None."""
    for step in steps:
        if value is None:
            return None
        if isinstance(value, list):
            index = step_index(step)
            if index is None or index >= len(value):
                return None
            value = value[index]
        elif isinstance(value, dict):
            key = step_key(step)
            if key not in value:
                return None
            value = value[key]
        else:
            return None
    return value


def leaf_comparable(value):
    """Sort-key component for a value reached through a field path."""
    if value is None:
        return NULL_COMP
    if isinstance(value, bool):
        return (RANK_NUMBER, 1 if value else 0)
    if isinstance(value, Timestamp):
        return (RANK_TIMESTAMP, value.dt)
    if isinstance(value, _date):
        return (RANK_DATE, value)
    if isinstance(value, (int, float)):
        return (RANK_NUMBER, value)
    return (RANK_STRING, typed_text(value))


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


def value_bits(value):
    """Types an observed value fits, or None when it is not an observation."""
    if value is NULL:
        return None
    if isinstance(value, str):
        if value == "":
            return None
        return candidate_bits(value)
    if isinstance(value, bool):
        return BOOL_BITS
    if isinstance(value, int):
        return INT_BITS
    if isinstance(value, float):
        return FLOAT_BITS
    if isinstance(value, Timestamp):
        return TS_BITS
    if isinstance(value, _date):
        return DATE_BITS
    return STRING_ONLY


def top_type(bits):
    for name in TYPE_PRIORITY:
        if bits & TYPE_BIT[name]:
            return name
    return STRING


def widen(masks):
    """Simplest type able to hold every observed value (T21)."""
    bits = ALL_BITS
    for mask in masks:
        bits &= mask
    chosen = top_type(bits)
    if chosen == STRING:
        # Every date is representable as a timestamp, which the per-value bit
        # sets (deliberately) do not encode, so promote that one pairing.
        kinds = {top_type(mask) for mask in masks}
        if kinds and kinds <= {DATE, TIMESTAMP}:
            return TIMESTAMP
    return chosen


def resolve_column_type(entries, strategy, infer_mode):
    """entries: list of (format rank, bitmask) for the files that saw the column."""
    if not entries:
        return STRING
    masks = [mask for _rank, mask in entries]
    if strategy == "union":
        return widen(masks)
    if strategy == "consensus":
        votes = {}
        for mask in masks:
            name = top_type(mask)
            votes[name] = votes.get(name, 0) + 1
        best = max(votes.values())
        tied = [name for name in TYPE_PRIORITY if votes.get(name, 0) == best]
        return tied[0]
    # authoritative: only the highest-precedence tier that saw the column votes.
    best_rank = min(rank for rank, _mask in entries)
    masks = [mask for rank, mask in entries if rank == best_rank]
    if infer_mode == "loose":
        return widen(masks)
    kinds = {top_type(mask) for mask in masks}
    return kinds.pop() if len(kinds) == 1 else STRING


# --------------------------------------------------------------------------
# Input specs: format & compression detection
# --------------------------------------------------------------------------


class InputSpec:
    __slots__ = ("path", "fmt", "compression", "scratch", "_local")

    def __init__(self, path, fmt, compression, scratch=None):
        self.path = path
        self.fmt = fmt
        self.compression = compression
        self.scratch = scratch
        self._local = None

    @property
    def rank(self):
        return FORMAT_RANK[self.fmt]

    def local_parquet_path(self):
        """A seekable, uncompressed copy of a gzipped parquet file."""
        if self.compression != "gzip":
            return self.path
        if self._local is None:
            handle = tempfile.NamedTemporaryFile(
                prefix="merge_files-", suffix=".parquet", dir=self.scratch,
                delete=False,
            )
            with handle:
                with gzip.open(self.path, "rb") as source:
                    shutil.copyfileobj(source, handle, 1024 * 1024)
            self._local = handle.name
        return self._local


def read_magic(path, length=4):
    try:
        with open(path, "rb") as handle:
            return handle.read(length)
    except OSError as exc:
        raise ToolError("cannot read input %s: %s" % (path, exc.strerror or exc))


def is_gzip_file(path):
    return read_magic(path, 2) == GZIP_MAGIC


def is_parquet_file(path, compression):
    if compression == "gzip":
        try:
            with gzip.open(path, "rb") as handle:
                return handle.read(4) == PARQUET_MAGIC
        except OSError:
            return False
    return read_magic(path, 4) == PARQUET_MAGIC


def resolve_compression(path, flag):
    actual = is_gzip_file(path)
    if flag == "gzip":
        if not actual:
            raise ToolError(
                "compression mismatch: %s is not gzip-compressed" % path,
                EXIT_DIALECT,
            )
        return "gzip"
    if flag == "none":
        if actual:
            raise ToolError(
                "compression mismatch: %s is gzip-compressed" % path, EXIT_DIALECT
            )
        return "none"
    # auto
    if path.lower().endswith(".gz") and not actual:
        raise ToolError(
            "compression mismatch: %s has a .gz suffix but is not gzip-compressed"
            % path,
            EXIT_DIALECT,
        )
    return "gzip" if actual else "none"


def resolve_format(path, flag, compression):
    if flag != "auto":
        return flag
    name = os.path.basename(path)
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    _stem, ext = os.path.splitext(lowered)
    fmt = EXT_FORMAT.get(ext)
    if fmt is not None:
        return fmt
    if is_parquet_file(path, compression):
        return PARQUET
    raise ToolError(
        "cannot determine input format for %s (use --input-format)" % path,
        EXIT_FORMAT,
    )


def make_specs(args, scratch):
    specs = []
    for path in args.inputs:
        if not os.path.exists(path):
            raise ToolError("input file not found: %s" % path)
        compression = resolve_compression(path, args.compression)
        fmt = resolve_format(path, args.input_format, compression)
        specs.append(InputSpec(path, fmt, compression, scratch))
    return specs


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


class Dialect:
    def __init__(self, quotechar, escapechar, null_literal):
        self.quotechar = quotechar
        self.escapechar = escapechar
        self.null_literal = null_literal


def open_text(spec, newline):
    try:
        if spec.compression == "gzip":
            binary = gzip.open(spec.path, "rb")
        else:
            binary = open(spec.path, "rb")
    except OSError as exc:
        raise ToolError(
            "cannot read input %s: %s" % (spec.path, exc.strerror or exc)
        )
    return io.TextIOWrapper(binary, encoding="utf-8-sig", newline=newline)


def wrap_os_error(spec, exc):
    return ToolError("cannot read input %s: %s" % (spec.path, exc))


def make_csv_reader(handle, dialect):
    return csv.reader(
        handle,
        delimiter=",",
        quotechar=dialect.quotechar,
        doublequote=True,
        escapechar=dialect.escapechar,
        strict=False,
    )


def is_null_text(cell, null_literal):
    if cell == "":
        return True
    return bool(null_literal) and cell == null_literal


def iter_delimited(spec, dialect):
    """Yield (line_number, header, cells) for a CSV or TSV input.

    The header is yielded once as the first item with cells set to None.
    """
    if spec.fmt == CSV:
        handle = open_text(spec, "")
        try:
            reader = make_csv_reader(handle, dialect)
            header = None
            line = 1
            for row in reader:
                if header is None:
                    header = list(row)
                    yield (1, header, None)
                    continue
                line += 1
                if not row:
                    continue
                yield (line, header, row)
            if header is None:
                yield (1, [], None)
        except csv.Error as exc:
            raise ToolError(
                "%s: malformed CSV: %s" % (spec.path, exc), EXIT_DIALECT
            )
        finally:
            handle.close()
        return

    handle = open_text(spec, "\n")
    try:
        header = None
        line = 0
        for raw in handle:
            line += 1
            text = raw.rstrip("\n")
            if text.endswith("\r"):
                text = text[:-1]
            if header is None:
                header = text.split("\t")
                yield (1, header, None)
                continue
            if text == "":
                continue
            cells = text.split("\t")
            if len(cells) > len(header):
                raise ToolError(
                    "%s:%d: literal tab inside a TSV field (%d fields, header has %d)"
                    % (spec.path, line, len(cells), len(header)),
                    EXIT_DIALECT,
                )
            yield (line, header, cells)
        if header is None:
            raise ToolError(
                "%s: TSV input has no header row" % spec.path, EXIT_DIALECT
            )
    finally:
        handle.close()


def header_positions(header, columns):
    lookup = {}
    for pos, name in enumerate(header):
        lookup.setdefault(name, pos)
    return [lookup.get(name) for name in columns]


def iter_jsonl(spec, allow_nested=False):
    """Yield (line_number, dict) for each JSON object in a JSONL input."""
    handle = open_text(spec, "\n")
    try:
        line = 0
        for raw in handle:
            line += 1
            text = raw.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except ValueError as exc:
                raise ToolError(
                    "%s:%d: invalid JSON: %s" % (spec.path, line, exc), EXIT_DIALECT
                )
            if not isinstance(record, dict):
                raise ToolError(
                    "%s:%d: JSONL line is not a JSON object" % (spec.path, line),
                    EXIT_DIALECT,
                )
            if not allow_nested:
                for name, value in record.items():
                    if isinstance(value, (list, dict)):
                        raise ToolError(
                            "nested structure requires provided --schema "
                            "(file=%s line=%d field=%s)" % (spec.path, line, name),
                            EXIT_NESTED,
                        )
            yield line, {
                name: jsonl_value(value) for name, value in record.items()
            }
    finally:
        handle.close()


def jsonl_value(value):
    if value is None:
        return NULL
    if isinstance(value, float):
        # Prefer int for integral numbers inside the int64 range (T24).
        if math.isfinite(value) and value.is_integer() and abs(value) <= INT64_MAX:
            return int(value)
    return value


def import_pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet as parquet
        import pyarrow.types as types
    except ImportError as exc:
        raise ToolError("reading Parquet input requires pyarrow: %s" % exc)
    return parquet, types


def parquet_file(spec, allow_nested=False):
    parquet, types = import_pyarrow()
    path = spec.local_parquet_path()
    try:
        handle = parquet.ParquetFile(path)
    except Exception as exc:
        raise ToolError(
            "%s: cannot read Parquet file: %s" % (spec.path, exc), EXIT_DIALECT
        )
    schema = handle.schema_arrow
    if not allow_nested:
        for field in schema:
            if types.is_nested(field.type):
                raise ToolError(
                    "nested structure requires provided --schema "
                    "(file=%s field=%s type=%s)"
                    % (spec.path, field.name, field.type),
                    EXIT_NESTED,
                )
    return handle, schema, types


def arrow_bits(field_type, types):
    """Bitmask for a Parquet column type, or None when values must be sniffed."""
    if types.is_boolean(field_type):
        return BOOL_BITS
    if types.is_integer(field_type):
        return INT_BITS
    if types.is_floating(field_type) or types.is_decimal(field_type):
        return FLOAT_BITS
    if types.is_date(field_type):
        return DATE_BITS
    if types.is_timestamp(field_type):
        return TS_BITS
    if (
        types.is_string(field_type)
        or types.is_large_string(field_type)
        or types.is_binary(field_type)
        or types.is_large_binary(field_type)
    ):
        return None
    return STRING_ONLY


def parquet_batch_rows(args):
    rows = max(1, args.parquet_row_group_bytes // 1024)
    budget = max(1, (args.memory_limit_mb * 1024 * 1024) // 4096)
    return max(1, min(rows, budget, 65536))


def convert_parquet(value):
    if value is None:
        return NULL
    if isinstance(value, datetime):
        return timestamp_from_datetime(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def make_parquet_converter(field_type, types):
    """Python-value converter for one Arrow type, nested types included."""
    if types.is_struct(field_type):
        subs = [
            (field.name, make_parquet_converter(field.type, types))
            for field in field_type
        ]

        def convert_struct(value):
            if value is None:
                return NULL
            return dict(
                (name, convert(value.get(name))) for name, convert in subs
            )

        return convert_struct
    if (
        types.is_list(field_type)
        or types.is_large_list(field_type)
        or types.is_fixed_size_list(field_type)
    ):
        inner = make_parquet_converter(field_type.value_type, types)

        def convert_list(value):
            if value is None:
                return NULL
            return [inner(item) for item in value]

        return convert_list
    if types.is_map(field_type):
        inner = make_parquet_converter(field_type.item_type, types)

        def convert_map(value):
            if value is None:
                return NULL
            out = {}
            for key, item in value:
                out[key if isinstance(key, str) else typed_text(key)] = inner(item)
            return out

        return convert_map
    return convert_parquet


def iter_parquet(spec, args, columns, allow_nested=False):
    """Yield (row_number, values) with values aligned to `columns`."""
    handle, schema, types = parquet_file(spec, allow_nested)
    names = list(schema.names)
    wanted = [name for name in columns if name in names]
    converters = [
        make_parquet_converter(schema.field(name).type, types) for name in wanted
    ]
    index = {name: pos for pos, name in enumerate(wanted)}
    positions = [index.get(name) for name in columns]
    blank = [NULL] * len(columns)
    row = 0
    try:
        if not wanted:
            for batch in handle.iter_batches(batch_size=parquet_batch_rows(args)):
                for _ in range(batch.num_rows):
                    row += 1
                    yield row, list(blank)
            return
        for batch in handle.iter_batches(
            batch_size=parquet_batch_rows(args), columns=wanted
        ):
            chunks = [column.to_pylist() for column in batch.columns]
            for offset in range(batch.num_rows):
                row += 1
                values = [
                    NULL if pos is None else converters[pos](chunks[pos][offset])
                    for pos in positions
                ]
                yield row, values
    finally:
        handle.close()


# --------------------------------------------------------------------------
# Per-file scanning for inference
# --------------------------------------------------------------------------


def scan_file(spec, args, dialect):
    """One pass over an input: (field names, {name: bitmask of fitting types})."""
    if spec.fmt == PARQUET:
        return scan_parquet(spec, args)
    masks = {}
    if spec.fmt == JSONL:
        names = []
        seen = set()
        for _line, record in iter_jsonl(spec):
            for name, value in record.items():
                if name not in seen:
                    seen.add(name)
                    names.append(name)
                observe(masks, name, value_bits(value))
        return names, masks

    names = None
    for _line, header, cells in iter_delimited(spec, dialect):
        if cells is None:
            names = header
            continue
        for pos, name in enumerate(names):
            if pos >= len(cells):
                break
            cell = cells[pos]
            if is_null_text(cell, dialect.null_literal):
                continue
            observe(masks, name, candidate_bits(cell))
    return names or [], masks


def observe(masks, name, bits):
    if bits is None:
        return
    previous = masks.get(name, ALL_BITS)
    # `string` fits everything, so it is the floor: once a column is down to it,
    # further values cannot narrow it.
    if previous != STRING_ONLY:
        previous &= bits
    masks[name] = previous


def scan_parquet(spec, args):
    """Parquet types come from the file schema; only string columns are sniffed."""
    handle, schema, types = parquet_file(spec)
    names = list(schema.names)
    masks = {}
    sniff = []
    for field in schema:
        bits = arrow_bits(field.type, types)
        if bits is None:
            sniff.append(field.name)
            masks[field.name] = STRING_ONLY
        else:
            masks[field.name] = bits
    try:
        if sniff:
            for name in sniff:
                masks.pop(name, None)
            for batch in handle.iter_batches(
                batch_size=parquet_batch_rows(args), columns=sniff
            ):
                for position, name in enumerate(sniff):
                    column = batch.column(position).to_pylist()
                    for value in column:
                        observe(masks, name, value_bits(convert_parquet(value)))
            for name in sniff:
                masks.setdefault(name, STRING_ONLY)
    finally:
        handle.close()
    return names, masks


def iter_rows(spec, args, dialect, columns, allow_nested=False):
    """Yield (line number, values aligned to `columns`) for one input."""
    if spec.fmt == PARQUET:
        for item in iter_parquet(spec, args, columns, allow_nested):
            yield item
        return
    if spec.fmt == JSONL:
        for line, record in iter_jsonl(spec, allow_nested):
            yield line, [record.get(name, NULL) for name in columns]
        return
    positions = None
    null_literal = dialect.null_literal
    for line, header, cells in iter_delimited(spec, dialect):
        if cells is None:
            positions = header_positions(header, columns)
            continue
        size = len(cells)
        values = []
        for pos in positions:
            if pos is None or pos >= size:
                values.append(NULL)
                continue
            cell = cells[pos]
            values.append(NULL if is_null_text(cell, null_literal) else cell)
        yield line, values


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
# Schema resolution
# --------------------------------------------------------------------------


def load_json_document(source, kind):
    """`source` is a path to a JSON document, or the document itself (T28)."""
    if not os.path.exists(source) and source.lstrip().startswith("{"):
        try:
            return json.loads(source), "<inline>"
        except ValueError as exc:
            raise ToolError(
                "invalid inline %s JSON: %s" % (kind, exc), EXIT_SCHEMA
            )
    try:
        with open(source, "r", encoding="utf-8") as handle:
            return json.load(handle), source
    except OSError as exc:
        raise ToolError(
            "cannot read %s %s: %s" % (kind, source, exc.strerror or exc)
        )
    except ValueError as exc:
        raise ToolError(
            "invalid %s JSON in %s: %s" % (kind, source, exc), EXIT_SCHEMA
        )


def parse_schema_document(document, origin, aliases):
    if not isinstance(document, dict) or not isinstance(
        document.get("columns"), list
    ):
        raise ToolError(
            "schema %s must be an object with a 'columns' list" % origin, EXIT_SCHEMA
        )
    columns = []
    types = {}
    for entry in document["columns"]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ToolError(
                "schema column entries need a 'name': %r" % (entry,), EXIT_SCHEMA
            )
        name = entry["name"]
        columns.append(name)
        types[name] = parse_type(
            entry.get("type", STRING), aliases, 'column "%s"' % name
        )
    return columns, types


def load_schema(source, aliases):
    document, origin = load_json_document(source, "schema")
    return parse_schema_document(document, origin, aliases)


def resolve_schema(specs, args, dialect, aliases):
    if args.schema:
        return load_schema(args.schema, aliases)
    names = set()
    per_file = []
    for spec in specs:
        file_names, masks = scan_file(spec, args, dialect)
        names.update(file_names)
        names.update(masks)
        per_file.append((spec.rank, masks))
    columns = sorted(names)
    types = {}
    for name in columns:
        entries = [
            (rank, masks[name]) for rank, masks in per_file if name in masks
        ]
        types[name] = resolve_column_type(
            entries, args.schema_strategy, args.infer
        )
    return columns, types


# --------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------


def cast_nested_cell(value, type_obj, name, policy, origin, null_literal, from_text):
    """Cell text and cast tree for a nested/`json` column."""
    if value is NULL:
        return null_literal, None
    raw = value
    if from_text and isinstance(value, str):
        try:
            raw = json.loads(value)
        except ValueError:
            # The cell is not a single JSON literal (T45).
            if policy == "fail":
                raise cast_error(value, type_obj, name, origin[0], origin[1])
            if policy == "keep-string":
                return value, None
            return null_literal, None
    tree = cast_nested(raw, type_obj, name, policy, origin)
    if tree is None:
        return null_literal, None
    if isinstance(tree, KeptString):
        # keep-string collapsed the whole column value to text (T52).
        return str(tree), None
    return canonical_json(tree), tree


def build_records(specs, args, columns, types, dialect, sorter):
    """Cast every input cell, feeding sortable records to the sorter."""
    null_literal = dialect.null_literal
    policy = args.on_type_error
    column_types = [types[name] for name in columns]
    nested = [not is_primitive(type_obj) for type_obj in column_types]
    casters = [
        CASTERS[type_obj] if is_primitive(type_obj) else None
        for type_obj in column_types
    ]
    key_paths = args.key_paths
    part_paths = args.partition_paths
    track_nulls = bool(part_paths)
    allow_nested = bool(args.schema)
    seq = 0
    for spec in specs:
        from_text = spec.fmt in (CSV, TSV)
        for line, values in iter_rows(spec, args, dialect, columns, allow_nested):
            origin = (spec.path, line)
            out_row = []
            comps = []
            trees = []
            nulls = set()
            for offset, value in enumerate(values):
                name = columns[offset]
                type_obj = column_types[offset]
                if nested[offset]:
                    text, tree = cast_nested_cell(
                        value, type_obj, name, policy, origin, null_literal,
                        from_text,
                    )
                    out_row.append(text)
                    trees.append(tree)
                    comps.append(NULL_COMP if tree is None else (RANK_STRING, text))
                    if tree is None and track_nulls:
                        nulls.add(offset)
                    continue
                trees.append(None)
                if value is NULL:
                    out_row.append(null_literal)
                    comps.append(NULL_COMP)
                    if track_nulls:
                        nulls.add(offset)
                    continue
                if isinstance(value, (dict, list)):
                    # Nested input in a column the schema declares flat.
                    text = json_text_of(value)
                    if policy == "fail":
                        raise cast_error(text, type_obj, name, spec.path, line)
                    if policy == "keep-string":
                        out_row.append(text)
                        comps.append((RANK_STRING, text))
                    else:
                        out_row.append(null_literal)
                        comps.append(NULL_COMP)
                        if track_nulls:
                            nulls.add(offset)
                    continue
                text = value if isinstance(value, str) else typed_text(value)
                try:
                    cast = text if type_obj == STRING else casters[offset](text)
                except CastError:
                    if policy == "fail":
                        raise cast_error(text, type_obj, name, spec.path, line)
                    if policy == "keep-string":
                        out_row.append(text)
                        comps.append((RANK_STRING, text))
                    else:
                        out_row.append(null_literal)
                        comps.append(NULL_COMP)
                        if track_nulls:
                            nulls.add(offset)
                    continue
                out_row.append(format_value(type_obj, cast))
                comps.append(comparable(type_obj, cast))
            key = tuple(
                path_component(path, comps, trees, "key") for path in key_paths
            )
            if track_nulls:
                segments = []
                for path in part_paths:
                    segments.append(
                        (path.text, path_text(path, out_row, trees, nulls))
                    )
                part_dir = partition_dir(segments)
            else:
                part_dir = ""
            sorter.add((key, seq, out_row, part_dir))
            seq += 1


def path_leaf(path, trees, label):
    """The primitive value a path with steps reaches in this row."""
    value = navigate(trees[path.position], path.steps)
    if isinstance(value, (dict, list)):
        raise path_error(path.text, label)
    return value


def path_component(path, comps, trees, label):
    if not path.steps:
        return comps[path.position]
    return leaf_comparable(path_leaf(path, trees, label))


def path_text(path, out_row, trees, nulls):
    """Partition value text for a path, or None when the fragment is null."""
    if not path.steps:
        if path.position in nulls:
            return None
        return out_row[path.position]
    value = path_leaf(path, trees, "partition")
    return None if value is None else typed_text(value)


def make_writer(stream, dialect):
    # The quote character is honoured on output; escaping stays doubling, so the
    # escape character is an input-side concession only (T29).
    return csv.writer(
        stream,
        delimiter=",",
        quotechar=dialect.quotechar,
        doublequote=True,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )


def write_rows(stream, columns, records, dialect):
    writer = make_writer(stream, dialect)
    writer.writerow(columns)
    for record in records:
        writer.writerow(record[2])
    stream.flush()


def write_output(destination, columns, records, dialect):
    if destination == "-":
        stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", newline="", write_through=True
        )
        try:
            write_rows(stream, columns, records, dialect)
        finally:
            try:
                stream.detach()
            except Exception:
                pass
        return

    folder = os.path.dirname(os.path.abspath(destination))
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=folder,
            prefix=".merge_files-", suffix=".tmp", delete=False,
        )
    except OSError as exc:
        raise ToolError(
            "cannot write output %s: %s" % (destination, exc.strerror or exc)
        )
    temp_name = handle.name
    try:
        with handle:
            write_rows(handle, columns, records, dialect)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Partitioned output
# --------------------------------------------------------------------------

# Characters a Hive-style partition value may carry literally; everything else
# is percent-encoded byte by byte, upper-case hex (T36).
PART_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
PART_BYTE = [
    chr(b) if chr(b) in PART_SAFE else "%%%02X" % b for b in range(256)
]

NULL_SEGMENT = "_null"
PART_NAME = "part-%05d.csv"

# Upper bound on partition files held open at once. The sorted stream visits
# partitions in whatever order the key dictates, so a partition may be revisited
# long after it was last written; evicted files are reopened for append.
MAX_OPEN_PARTS = 32


def encode_partition_value(text):
    if not text:
        return text
    for char in text:
        if char not in PART_SAFE:
            break
    else:
        return text
    return "".join(PART_BYTE[byte] for byte in text.encode("utf-8"))


def partition_dir(segments):
    """Relative directory for one row: `col=val/col2=val2` (T35, T37, T43, T50)."""
    parts = []
    for name, text in segments:
        value = NULL_SEGMENT if text is None else encode_partition_value(text)
        parts.append(name + "=" + value)
    return "/".join(parts)


class PartitionState:
    """Per-directory cursor: which part file, and how full it is."""

    __slots__ = ("directory", "index", "rows", "size", "handle", "made")

    def __init__(self, directory):
        self.directory = directory
        self.index = -1
        self.rows = 0
        self.size = 0
        self.handle = None
        self.made = False


class PartitionedWriter:
    """Fan the sorted stream out into `part-xxxxx.csv` files under `root`."""

    def __init__(self, root, columns, dialect, max_rows, max_bytes, by_field):
        self.root = root
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.by_field = by_field
        self.buffer = io.StringIO()
        self.writer = make_writer(self.buffer, dialect)
        self.header = self.render(columns)
        self.header_size = byte_length(self.header)
        self.states = {}
        self.open_states = OrderedDict()

    def render(self, row):
        buffer = self.buffer
        buffer.seek(0)
        buffer.truncate(0)
        self.writer.writerow(row)
        return buffer.getvalue()

    def directory_path(self, state):
        if not state.directory:
            return self.root
        return os.path.join(self.root, *state.directory.split("/"))

    def part_path(self, state):
        return os.path.join(self.directory_path(state), PART_NAME % state.index)

    def open_next(self, state):
        """Close the current part and start the next one, header first."""
        self.close(state)
        state.index += 1
        folder = self.directory_path(state)
        if not state.made:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as exc:
                raise ToolError(
                    "cannot create partition directory %s: %s"
                    % (state.directory or ".", exc.strerror or exc)
                )
            state.made = True
        handle = self.open_file(self.part_path(state), "w")
        handle.write(self.header)
        state.handle = handle
        state.rows = 0
        state.size = self.header_size
        self.open_states[state.directory] = state
        self.evict()

    def open_file(self, path, mode):
        try:
            return open(path, mode, encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(
                "cannot write output file %s: %s" % (path, exc.strerror or exc)
            )

    def handle_for(self, state):
        if state.handle is not None:
            self.open_states.move_to_end(state.directory)
            return state.handle
        state.handle = self.open_file(self.part_path(state), "a")
        self.open_states[state.directory] = state
        self.evict()
        return state.handle

    def evict(self):
        while len(self.open_states) > MAX_OPEN_PARTS:
            _key, victim = self.open_states.popitem(last=False)
            self.shut(victim)

    def shut(self, state):
        handle, state.handle = state.handle, None
        if handle is not None:
            handle.close()

    def close(self, state):
        self.open_states.pop(state.directory, None)
        self.shut(state)

    def add(self, directory, row):
        state = self.states.get(directory)
        if state is None:
            state = self.states[directory] = PartitionState(directory)
        text = self.render(row)
        size = byte_length(text)
        if state.index < 0:
            self.open_next(state)
        elif self.should_cut(state, size):
            self.open_next(state)
        self.handle_for(state).write(text)
        state.rows += 1
        state.size += size

    def should_cut(self, state, size):
        """Cut before the row that would breach either limit (T40)."""
        if self.max_rows is not None and state.rows + 1 > self.max_rows:
            return True
        if self.max_bytes is not None and state.rows > 0:
            if state.size + size > self.max_bytes:
                return True
        return False

    def finish(self):
        # A sharded stream with no field partitioning is still one output, so
        # it keeps its header-only `part-00000.csv` (T39).
        if not self.states and not self.by_field:
            self.open_next(self.states.setdefault("", PartitionState("")))
        self.close_all()

    def close_all(self):
        for state in self.states.values():
            self.shut(state)
        self.open_states.clear()


def byte_length(text):
    return len(text) if text.isascii() else len(text.encode("utf-8"))


def install_directory(staging, destination):
    """Move `staging` into place as `destination`, replacing what was there."""
    try:
        os.rename(staging, destination)
        return
    except OSError:
        pass
    if not os.path.isdir(destination):
        raise ToolError(
            "output %s exists and is not a directory" % destination
        )
    parent = os.path.dirname(destination)
    try:
        trash = tempfile.mkdtemp(prefix=".merge_files-old-", suffix=".tmp", dir=parent)
    except OSError as exc:
        raise ToolError(
            "cannot replace output directory %s: %s"
            % (destination, exc.strerror or exc)
        )
    retired = os.path.join(trash, "old")
    try:
        os.rename(destination, retired)
    except OSError as exc:
        shutil.rmtree(trash, ignore_errors=True)
        raise ToolError(
            "cannot replace output directory %s: %s"
            % (destination, exc.strerror or exc)
        )
    try:
        os.rename(staging, destination)
    except OSError as exc:
        try:
            os.rename(retired, destination)
        except OSError:
            pass
        shutil.rmtree(trash, ignore_errors=True)
        raise ToolError(
            "cannot replace output directory %s: %s"
            % (destination, exc.strerror or exc)
        )
    shutil.rmtree(trash, ignore_errors=True)


def write_partitioned(destination, columns, records, dialect, args):
    """Directory mode: build everything in a sibling temp dir, then install it."""
    target = os.path.abspath(destination)
    parent = os.path.dirname(target)
    if os.path.exists(target) and not os.path.isdir(target):
        raise ToolError("output %s exists and is not a directory" % destination)
    try:
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".merge_files-", suffix=".tmp", dir=parent)
    except OSError as exc:
        raise ToolError(
            "cannot create output directory %s: %s"
            % (destination, exc.strerror or exc)
        )
    writer = PartitionedWriter(
        staging, columns, dialect, args.max_rows_per_file,
        args.max_bytes_per_file, bool(args.partition_by),
    )
    try:
        for record in records:
            writer.add(record[3], record[2])
        writer.finish()
    except BaseException:
        writer.close_all()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    try:
        install_directory(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def partitioning_requested(args):
    return bool(
        args.partition_by
        or args.max_rows_per_file is not None
        or args.max_bytes_per_file is not None
    )


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
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
    )
    parser.add_argument("--output", required=True, help="output path, or - for stdout")
    parser.add_argument(
        "--key",
        required=True,
        action="append",
        help="comma-separated sort key column(s)",
    )
    parser.add_argument(
        "--partition-by",
        action="append",
        help="comma-separated column(s) to partition output directories by",
    )
    parser.add_argument(
        "--max-rows-per-file", type=positive_int, default=None,
        help="cut each output file after this many data rows",
    )
    parser.add_argument(
        "--max-bytes-per-file", type=positive_int, default=None,
        help="cut each output file before it would exceed this many bytes",
    )
    parser.add_argument(
        "--desc", action="store_true", help="sort all key columns descending"
    )
    parser.add_argument("--schema", help="JSON file (or document) with the schema")
    parser.add_argument(
        "--type-alias-file",
        help="JSON file (or document) of extra type aliases",
    )
    parser.add_argument(
        "--infer", choices=("strict", "loose"), default="strict",
        help="type inference mode when no schema is given",
    )
    parser.add_argument(
        "--schema-strategy",
        choices=("authoritative", "consensus", "union"),
        default="authoritative",
        help="how to reconcile conflicting types across inputs",
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
    parser.add_argument(
        "--input-format",
        choices=("auto", CSV, TSV, JSONL, PARQUET),
        default="auto",
    )
    parser.add_argument(
        "--compression", choices=("auto", "none", "gzip"), default="auto"
    )
    parser.add_argument(
        "--parquet-row-group-bytes", type=positive_int, default=128 * 1024 * 1024,
        help="advisory batch size when reading Parquet row groups",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT")
    return parser


def split_path_list(group):
    """Split on commas that are outside `[...]` and outside quotes."""
    parts = []
    buffer = []
    depth = 0
    quoted = False
    for char in group:
        if quoted:
            buffer.append(char)
            if char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth <= 0:
            parts.append("".join(buffer))
            buffer = []
            continue
        buffer.append(char)
    parts.append("".join(buffer))
    return parts


def parse_args(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    keys = []
    for group in args.key:
        for name in split_path_list(group):
            name = name.strip()
            if not name:
                parser.error("--key must name at least one field path")
            keys.append(name)
    args.key = keys
    parts = []
    for group in args.partition_by or []:
        for name in split_path_list(group):
            name = name.strip()
            if not name:
                parser.error("--partition-by must name at least one field path")
            parts.append(name)
    args.partition_by = parts
    args.key_paths = []
    args.partition_paths = []
    if args.temp_dir is not None and not os.path.isdir(args.temp_dir):
        parser.error("--temp-dir %s is not a directory" % args.temp_dir)
    if partitioning_requested(args) and args.output == "-":
        parser.error(
            "--output must be a directory path (not -) when --partition-by, "
            "--max-rows-per-file or --max-bytes-per-file is given"
        )
    return args


def run(args):
    dialect = Dialect(args.csv_quotechar, args.csv_escapechar, args.csv_null_literal)
    scratch = tempfile.mkdtemp(prefix="merge_files-", dir=args.temp_dir)
    sorter = ExternalSorter(scratch, args.memory_limit_mb, args.desc)
    try:
        aliases = load_aliases(args.type_alias_file)
        specs = make_specs(args, scratch)
        columns, types = resolve_schema(specs, args, dialect, aliases)
        # Key paths must name a primitive in the resolved schema; partition
        # paths answer to the same rule (T41).
        args.key_paths = [
            resolve_field_path(text, columns, types, "key") for text in args.key
        ]
        args.partition_paths = [
            resolve_field_path(text, columns, types, "partition")
            for text in args.partition_by
        ]
        build_records(specs, args, columns, types, dialect, sorter)
        if partitioning_requested(args):
            write_partitioned(
                args.output, columns, sorter.sorted_records(), dialect, args
            )
        else:
            write_output(args.output, columns, sorter.sorted_records(), dialect)
    finally:
        sorter.cleanup()
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except ToolError as exc:
        sys.stderr.write("%s: error: ERR %d %s\n" % (PROG, exc.code, exc))
        return exc.code
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_IO
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

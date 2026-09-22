"""The type expressions a schema can declare, and how they are written down.

A primitive is its own name (`"int"`), so everything that predates nested types
keeps working with plain strings; the nested kinds are small frozen records.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .aliases import Aliases
from .casting import TYPES
from .errors import EXIT_SCHEMA, MergeError


@dataclass(frozen=True)
class JsonAny:
    """A `json` column: any JSON value, normalized but never cast."""


@dataclass(frozen=True)
class Field:
    """One named member of a struct, in declaration order."""

    name: str
    type: "TypeExpr"


@dataclass(frozen=True)
class Struct:
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Array:
    element: "TypeExpr"


@dataclass(frozen=True)
class Map:
    """A `map<string,T>`; the key type is fixed by the spec, so only T is kept."""

    value: "TypeExpr"


TypeExpr = Union[str, JsonAny, Struct, Array, Map]

#: The one `json` value; `struct` with no fields resolves to it as well.
JSON = JsonAny()

#: Type names that need no parameters, including the nested kinds written bare.
_BARE_TYPES: dict[str, TypeExpr] = {
    **{name: name for name in TYPES},
    "json": JSON,
    "struct": JSON,
    "array": Array(JSON),
    "map": Map(JSON),
}


def is_primitive(expr: TypeExpr) -> bool:
    """Whether `expr` is one of the six primitive types."""
    return isinstance(expr, str)


def describe(expr: TypeExpr) -> str:
    """How a type is named in an error message."""
    if isinstance(expr, Struct):
        return "struct"
    if isinstance(expr, Array):
        return f"array<{describe(expr.element)}>"
    if isinstance(expr, Map):
        return f"map<string,{describe(expr.value)}>"
    return "json" if isinstance(expr, JsonAny) else expr


def parse_type(spec, aliases: Aliases) -> TypeExpr:
    """One `"type"` entry of a schema document, written as a name or as an object."""
    if isinstance(spec, str):
        return _named_type(spec, aliases)
    if isinstance(spec, dict) and len(spec) == 1:
        kind, body = next(iter(spec.items()))
        builder = _KIND_BUILDERS.get(kind.lower())
        if builder:
            return builder(body if isinstance(body, dict) else {}, aliases)
    raise MergeError(f"unusable type declaration {spec!r}", EXIT_SCHEMA)


def _named_type(text: str, aliases: Aliases) -> TypeExpr:
    """A type written as a name, after alias resolution: `int`, `list<int>`, ..."""
    head, arguments = _split_generic(aliases.resolve(text))
    if arguments is None:
        bare = _BARE_TYPES.get(head)
        if bare is None:
            raise MergeError(f"unknown type {text!r}", EXIT_SCHEMA)
        return bare
    if head == "array":
        return Array(_one_argument(text, arguments, aliases))
    if head == "map":
        return _generic_map(text, arguments, aliases)
    raise MergeError(f"unknown type {text!r}", EXIT_SCHEMA)


def _one_argument(text: str, arguments: str, aliases: Aliases) -> TypeExpr:
    parts = _split_arguments(arguments)
    if len(parts) != 1:
        raise MergeError(f"array takes one element type: {text!r}", EXIT_SCHEMA)
    return _named_type(parts[0], aliases)


def _generic_map(text: str, arguments: str, aliases: Aliases) -> Map:
    parts = _split_arguments(arguments)
    if len(parts) != 2 or not _is_string_key(parts[0], aliases):
        raise MergeError(f"map takes a string key and a value type: {text!r}", EXIT_SCHEMA)
    return Map(_named_type(parts[1], aliases))


def _struct_type(body: dict, aliases: Aliases) -> TypeExpr:
    """`{"struct": {"fields": [...]}}`; a struct without fields is any JSON."""
    entries = body.get("fields")
    if entries is None:
        return JSON
    fields = tuple(Field(_field_name(entry), parse_type(entry.get("type"), aliases))
                   for entry in entries)
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise MergeError(f"struct field names must be unique: {', '.join(names)}",
                         EXIT_SCHEMA)
    return Struct(fields) if fields else JSON


def _array_type(body: dict, aliases: Aliases) -> Array:
    return Array(parse_type(body.get("element"), aliases))


def _map_type(body: dict, aliases: Aliases) -> Map:
    key = body.get("key", "string")
    if not (isinstance(key, str) and _is_string_key(key, aliases)):
        raise MergeError(f"map keys must be strings, not {key!r}", EXIT_SCHEMA)
    return Map(parse_type(body.get("value"), aliases))


def _field_name(entry) -> str:
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise MergeError(f"struct field needs a name: {entry!r}", EXIT_SCHEMA)
    return entry["name"]


def _is_string_key(text: str, aliases: Aliases) -> bool:
    return _named_type(text, aliases) == "string"


def _split_generic(text: str) -> tuple[str, str | None]:
    """A type name split into its head and its `<...>` arguments, if any."""
    head, angle, rest = text.partition("<")
    if not angle:
        return head.strip(), None
    if not rest.endswith(">"):
        raise MergeError(f"unterminated type parameters in {text!r}", EXIT_SCHEMA)
    return head.strip(), rest[:-1]


def _split_arguments(arguments: str) -> list[str]:
    """Split `<...>` contents on the commas that are not inside nested parameters."""
    parts, depth, start = [], 0, 0
    for position, character in enumerate(arguments):
        depth += (character == "<") - (character == ">")
        if character == "," and depth == 0:
            parts.append(arguments[start:position])
            start = position + 1
    parts.append(arguments[start:])
    return [part.strip() for part in parts]


_KIND_BUILDERS = {"struct": _struct_type, "array": _array_type, "map": _map_type}

"""Turning the type a schema declares into the type the pipeline casts with.

A type is written either as a name — ``int``, ``timestamp``, ``json``, or a
generic such as ``array<int>`` and ``map<string,float>`` — or as the object
form that spells a nested type out:

    {"struct": {"fields": [{"name": "sku", "type": "string"}]}}
    {"array": {"element": {"map": {"key": "string", "value": "float"}}}}

Names are case insensitive and go through the aliases first: the built-in ones
below, plus whatever ``--type-alias-file`` adds.  An alias may name another
alias and is followed until it reaches a type, so a table is checked for cycles
when it is built rather than when a schema happens to use it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping

from casting import ValueType
from column_types import TYPES
from errors import SchemaError, UsageError
from nested_types import JSON, ArrayType, MapType, StructField, StructType

# Always accepted, whether or not an alias file is given.  ``list`` is the head
# of ``list<T>`` and of ``{"list": {"element": ...}}``, so aliasing it to
# ``array`` covers both forms.
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
}


class TypeAliases:
    """The names a type may be written under, resolved transitively."""

    def __init__(self, extra: Mapping[str, str] | None = None) -> None:
        added = {name.lower(): target for name, target in (extra or {}).items()}
        self._targets = {**BUILTIN_ALIASES, **added}
        for name in self._targets:
            self.resolve(name)

    def resolve(self, name: str) -> str:
        """Follow ``name`` through the aliases to the type name it stands for."""
        chain = [name.strip().lower()]
        while (target := self._targets.get(chain[-1])) is not None:
            if target.strip().lower() in chain:
                raise UsageError(f"type alias cycle: {' -> '.join([*chain, target])}")
            chain.append(target.strip().lower())
        return chain[-1]


def load_aliases(path: Path | None) -> TypeAliases:
    """Read ``--type-alias-file``: ``{"aliases": {"smallint": "int", ...}}``."""
    if path is None:
        return TypeAliases()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UsageError(f"{path}: invalid JSON ({error})") from error
    aliases = document.get("aliases") if isinstance(document, dict) else None
    if not isinstance(aliases, dict):
        raise UsageError(f"{path}: the alias file must be an object with an 'aliases' object")
    if not all(isinstance(target, str) for target in aliases.values()):
        raise UsageError(f"{path}: every alias must name a type")
    return TypeAliases(aliases)


def parse_type(
    spec: object, aliases: TypeAliases, field: str, trail: frozenset[str] = frozenset()
) -> ValueType:
    """Build the type ``spec`` declares for ``field``, which names it on error.

    ``trail`` holds the alias names already expanded, so an alias that ends up
    naming itself is caught instead of recursing.
    """
    if isinstance(spec, str):
        return _named(spec, aliases, field, trail)
    if isinstance(spec, dict) and len(spec) == 1:
        (kind, body), = spec.items()
        build = _NESTED.get(aliases.resolve(kind))
        if build is not None:
            return build(body, aliases, field)
    raise SchemaError(f"unknown column type {spec!r} for field {field!r}")


def _named(spec: str, aliases: TypeAliases, field: str, trail: frozenset[str]) -> ValueType:
    """Build the type a name stands for, following its aliases first."""
    name = aliases.resolve(spec)
    if name in trail:
        raise UsageError(f"type alias cycle: {spec} -> {name}")
    if "<" in name:
        return _generic(name, aliases, field, trail | {name})
    if name == JSON.name:
        return JSON
    if name not in TYPES:
        raise SchemaError(f"unknown column type {spec!r} for field {field!r}")
    return TYPES[name]


def _generic(name: str, aliases: TypeAliases, field: str, trail: frozenset[str]) -> ValueType:
    """Build ``array<T>`` or ``map<string,T>``, the compact form of a nested type."""
    head, _, arguments = name.partition("<")
    if name.endswith(">"):
        parts = _arguments(arguments[:-1])
        kind = aliases.resolve(head)
        if kind == "array" and len(parts) == 1:
            return ArrayType(parse_type(parts[0], aliases, field, trail))
        if kind == "map" and len(parts) == 2 and aliases.resolve(parts[0]) == "string":
            return MapType(parse_type(parts[1], aliases, field, trail))
    raise SchemaError(f"unknown column type {name!r} for field {field!r}")


def _arguments(text: str) -> list[str]:
    """Split a generic's arguments on the commas that are not inside another."""
    parts, depth, start = [], 0, 0
    for index, character in enumerate(text):
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    return [*parts, text[start:]]


def _struct(body: object, aliases: TypeAliases, field: str) -> StructType:
    """Build ``{"struct": {"fields": [{"name": ..., "type": ...}, ...]}}``."""
    entries = body.get("fields") if isinstance(body, dict) else None
    if not isinstance(entries, list) or not entries:
        raise SchemaError(f"the struct at field {field!r} needs a non-empty 'fields' list")
    fields = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            raise SchemaError(f"every field of the struct at {field!r} needs a 'name'")
        fields.append(StructField(name, parse_type(entry.get("type"), aliases, f"{field}.{name}")))
    names = [struct_field.name for struct_field in fields]
    if len(set(names)) != len(names):
        raise SchemaError(f"the struct at field {field!r} has duplicate field names")
    return StructType(tuple(fields))


def _array(body: object, aliases: TypeAliases, field: str) -> ArrayType:
    """Build ``{"array": {"element": <type>}}``."""
    if not isinstance(body, dict) or "element" not in body:
        raise SchemaError(f"the array at field {field!r} needs an 'element' type")
    return ArrayType(parse_type(body["element"], aliases, f"{field}.0"))


def _map(body: object, aliases: TypeAliases, field: str) -> MapType:
    """Build ``{"map": {"key": "string", "value": <type>}}``; keys are strings."""
    if not isinstance(body, dict) or "value" not in body:
        raise SchemaError(f"the map at field {field!r} needs a 'value' type")
    key = body.get("key", "string")
    if not isinstance(key, str) or aliases.resolve(key) != "string":
        raise SchemaError(f"the map at field {field!r} must have string keys")
    return MapType(parse_type(body["value"], aliases, f"{field}[]"))


_NESTED: dict[str, Callable[[object, TypeAliases, str], ValueType]] = {
    "struct": _struct,
    "array": _array,
    "map": _map,
}

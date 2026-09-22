"""The column types: the six primitives, and the nested kinds built on them.

A schema file spells a type either as a name (``"int"``, ``"array<int>"``, any
alias of those) or as an object (``{"array": {"element": ...}}``), and both
spellings parse to the same immutable type object. ``Json`` is the type of a
column declared ``json``: it accepts whatever JSON the input holds and is
never cast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Union

from csvmerge.aliases import Aliases
from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.values import TYPE_PRIORITY

PRIMITIVE_NAMES = frozenset(TYPE_PRIORITY)

STRUCT, ARRAY, MAP = "struct", "array", "map"

_GENERIC = re.compile(r"(?P<head>[^<>,]+)<(?P<args>.*)>", re.DOTALL)


@dataclass(frozen=True)
class Primitive:
    """One of ``string``, ``int``, ``float``, ``bool``, ``date``, ``timestamp``."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Field:
    """One named member of a struct."""

    name: str
    type: "DataType"


@dataclass(frozen=True)
class Struct:
    """An ordered list of named fields; the order is the output order."""

    fields: tuple[Field, ...]

    def __str__(self) -> str:
        return f"struct<{','.join(f'{field.name}:{field.type}' for field in self.fields)}>"


@dataclass(frozen=True)
class Array:
    """A list whose elements all share one type."""

    element: "DataType"

    def __str__(self) -> str:
        return f"array<{self.element}>"


@dataclass(frozen=True)
class Map:
    """An object with string keys and one type for all of its values."""

    value: "DataType"

    def __str__(self) -> str:
        return f"map<string,{self.value}>"


@dataclass(frozen=True)
class Json:
    """Any JSON value at all, kept as it came and only normalised."""

    def __str__(self) -> str:
        return "json"


DataType = Union[Primitive, Struct, Array, Map, Json]


def parse_type(spec: Any, aliases: Aliases, where: str, seen: tuple[str, ...] = ()) -> DataType:
    """Read one type out of a schema file, resolving aliases as it goes.

    ``where`` names what is being typed - a column, or a field inside one -
    and only appears in error messages.
    """
    if isinstance(spec, str):
        return _parse_name(spec, aliases, where, seen)
    if isinstance(spec, dict):
        return _parse_object(spec, aliases, where, seen)
    raise MergeError(
        f"{where}: a type must be a name or an object, found {type(spec).__name__}", EXIT_SCHEMA
    )


def _parse_name(text: str, aliases: Aliases, where: str, seen: tuple[str, ...]) -> DataType:
    """Read a type written as a name: ``int``, ``array<int>``, ``map<string,int>``."""
    generic = _GENERIC.fullmatch(text.strip())
    if generic is None:
        resolved, followed = aliases.resolve(text, seen)
        if resolved in PRIMITIVE_NAMES:
            return Primitive(resolved)
        if resolved == STRUCT:
            return Json()
        if "<" in resolved:
            return _parse_name(resolved, aliases, where, followed)
        raise MergeError(f"{where}: unknown type {text!r}", EXIT_SCHEMA)
    head, followed = aliases.resolve(generic["head"], seen)
    arguments = _split_arguments(generic["args"])
    if head == ARRAY and len(arguments) == 1:
        return Array(parse_type(arguments[0], aliases, where, followed))
    if head == MAP and len(arguments) == 2:
        _require_string_key(arguments[0], aliases, where, followed)
        return Map(parse_type(arguments[1], aliases, where, followed))
    raise MergeError(f"{where}: unknown type {text!r}", EXIT_SCHEMA)


def _parse_object(spec: dict, aliases: Aliases, where: str, seen: tuple[str, ...]) -> DataType:
    """Read a type written as ``{"<kind>": {...}}``."""
    if len(spec) != 1:
        raise MergeError(
            f"{where}: a nested type names exactly one of struct, array or map, "
            f"found {len(spec)} keys",
            EXIT_SCHEMA,
        )
    (written, body), = spec.items()
    kind, followed = aliases.resolve(written, seen)
    if kind == STRUCT:
        return _parse_struct(body["fields"], aliases, where, followed)
    if kind == ARRAY:
        return Array(parse_type(body["element"], aliases, where, followed))
    if kind == MAP:
        _require_string_key(body.get("key", "string"), aliases, where, followed)
        return Map(parse_type(body["value"], aliases, where, followed))
    raise MergeError(f"{where}: unknown nested type {written!r}", EXIT_SCHEMA)


def _parse_struct(fields: list, aliases: Aliases, where: str, seen: tuple[str, ...]) -> Struct:
    parsed = tuple(
        Field(entry["name"], parse_type(entry["type"], aliases, f"{where}.{entry['name']}", seen))
        for entry in fields
    )
    names = [field.name for field in parsed]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise MergeError(
            f"{where}: struct field name(s) {', '.join(duplicates)} appear more than once",
            EXIT_SCHEMA,
        )
    return Struct(parsed)


def _require_string_key(spec: Any, aliases: Aliases, where: str, seen: tuple[str, ...]) -> None:
    """Refuse a map whose keys are anything but strings."""
    if parse_type(spec, aliases, where, seen) != Primitive("string"):
        raise MergeError(f"{where}: a map key must be a string, not {spec!r}", EXIT_SCHEMA)


def _split_arguments(text: str) -> list[str]:
    """Split ``string,array<int>`` on the commas that are not inside ``<>``."""
    arguments: list[str] = []
    depth = 0
    start = 0
    for position, character in enumerate(text):
        depth += (character == "<") - (character == ">")
        if character == "," and depth == 0:
            arguments.append(text[start:position])
            start = position + 1
    arguments.append(text[start:])
    return arguments

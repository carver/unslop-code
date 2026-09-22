"""The declared type of a column: the six primitives plus the nested kinds.

Types are read from `--schema`, either as a name (`int`, `list<int>`,
`map<string,json>`) or as the single-key object the spec documents. A bare
`struct` — which the built-in `json` alias resolves to — accepts any JSON value
(ambiguity T50).
"""

from __future__ import annotations

from dataclasses import dataclass

from csvmerge.aliases import AliasTable, TypeName
from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.types import TYPES, ColumnType

STRUCT = "struct"
ARRAY = "array"
MAP = "map"


@dataclass(frozen=True)
class Primitive:
    """One of `string`, `int`, `float`, `bool`, `date` and `timestamp`."""

    name: str

    @property
    def definition(self) -> ColumnType:
        """How values of this type parse, render and compare."""
        return TYPES[self.name]

    @property
    def text(self) -> str:
        return self.name


@dataclass(frozen=True)
class Struct:
    """An ordered list of named fields with types of their own."""

    fields: tuple["Field", ...]

    @property
    def text(self) -> str:
        return STRUCT


@dataclass(frozen=True)
class Array:
    """A homogeneous list of `element`."""

    element: "DataType"

    @property
    def text(self) -> str:
        return f"{ARRAY}<{self.element.text}>"


@dataclass(frozen=True)
class Map:
    """A mapping from string keys to `value`."""

    value: "DataType"

    @property
    def text(self) -> str:
        return f"{MAP}<string,{self.value.text}>"


@dataclass(frozen=True)
class AnyJson:
    """The `json` type: any JSON value, normalised but never cast."""

    @property
    def text(self) -> str:
        return "json"


DataType = Primitive | Struct | Array | Map | AnyJson


@dataclass(frozen=True)
class Field:
    """One named field of a struct."""

    name: str
    type: DataType


def parse_type(declaration: object, aliases: AliasTable, where: str) -> DataType:
    """Build the type `where` declares, from its name or its object form."""
    if isinstance(declaration, str):
        return _named(aliases.resolve(declaration), declaration, aliases, where)
    if isinstance(declaration, dict) and len(declaration) == 1:
        ((kind, body),) = declaration.items()
        return _structured(aliases.resolve(str(kind)).head, body, aliases, where)
    raise MergeError(
        f"{where}: type must be a name or a single-key object, got {declaration!r}",
        EXIT_SCHEMA,
    )


def _named(
    name: TypeName, declaration: str, aliases: AliasTable, where: str
) -> DataType:
    """A type written as text, such as `int`, `list<int>` or `map<string,int>`."""
    if name.args is None:
        if name.head in TYPES:
            return Primitive(name.head)
        if name.head == STRUCT:
            return AnyJson()
    elif name.head == ARRAY and len(name.args) == 1:
        return Array(parse_type(name.args[0], aliases, where))
    elif name.head == MAP and len(name.args) == 2:
        return _map(name.args[0], name.args[1], aliases, where)
    raise MergeError(f"{where}: unknown type {declaration!r}", EXIT_SCHEMA)


def _structured(kind: str, body: object, aliases: AliasTable, where: str) -> DataType:
    """A type written as an object, such as `{"array": {"element": "int"}}`."""
    if isinstance(body, dict):
        if kind == STRUCT:
            return _struct(body, aliases, where)
        if kind == ARRAY and "element" in body:
            return Array(parse_type(body["element"], aliases, where))
        if kind == MAP and {"key", "value"} <= body.keys():
            return _map(body["key"], body["value"], aliases, where)
    raise MergeError(
        f"{where}: unknown or malformed {kind!r} type declaration", EXIT_SCHEMA
    )


def _struct(body: dict, aliases: AliasTable, where: str) -> Struct:
    """A struct's ordered fields; names are unique within one struct."""
    entries = body.get("fields")
    if not isinstance(entries, list):
        raise MergeError(f"{where}: struct needs a 'fields' list", EXIT_SCHEMA)
    fields = tuple(_field(entry, aliases, where) for entry in entries)
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise MergeError(f"{where}: struct field names must be unique", EXIT_SCHEMA)
    return Struct(fields)


def _field(entry: object, aliases: AliasTable, where: str) -> Field:
    """One entry of a struct's "fields" list."""
    if not isinstance(entry, dict) or "name" not in entry or "type" not in entry:
        raise MergeError(
            f"{where}: struct field needs 'name' and 'type': {entry!r}", EXIT_SCHEMA
        )
    name = str(entry["name"])
    return Field(name, parse_type(entry["type"], aliases, f"{where}.{name}"))


def _map(key: object, value: object, aliases: AliasTable, where: str) -> Map:
    """A map; the spec allows string keys only."""
    if parse_type(key, aliases, where) != Primitive("string"):
        raise MergeError(f"{where}: map keys must be strings, got {key!r}", EXIT_SCHEMA)
    return Map(parse_type(value, aliases, where))

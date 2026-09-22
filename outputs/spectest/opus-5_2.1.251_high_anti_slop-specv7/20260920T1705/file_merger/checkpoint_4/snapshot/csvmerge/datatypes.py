"""The types a schema column may declare: the primitives, plus nesting.

A declared type is either a :class:`ColumnType` primitive, one of the three
nested kinds (:class:`StructType`, :class:`ArrayType`, :class:`MapType`) or
:data:`JSON`, the flexible type that accepts any JSON value.  ``parse_type``
builds one of these from the JSON a ``--schema`` file spells it with, taking
every type name through the alias table first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Union

from .aliases import AliasTable
from .coltypes import ColumnType
from .errors import SchemaError


class JsonType:
    """The ``json`` type: any JSON value, carried through without casting."""

    def __repr__(self) -> str:
        return "json"


#: The single ``json`` instance; the type carries no parameters.
JSON = JsonType()


@dataclass(frozen=True)
class StructField:
    """One named member of a struct, in the order the schema declares it."""

    name: str
    type: "DataType"


@dataclass(frozen=True)
class StructType:
    fields: tuple[StructField, ...]

    def field(self, name: str) -> StructField | None:
        return next((field for field in self.fields if field.name == name), None)


@dataclass(frozen=True)
class ArrayType:
    element: "DataType"


@dataclass(frozen=True)
class MapType:
    """A map from string keys to ``value``; JSON objects only have string keys."""

    value: "DataType"


DataType = Union[ColumnType, JsonType, StructType, ArrayType, MapType]

_PRIMITIVE_NAMES = {member.value for member in ColumnType}


def is_primitive(datatype: DataType) -> bool:
    """Whether a type holds a single value rather than a nested structure."""
    return isinstance(datatype, ColumnType)


def type_name(datatype: DataType) -> str:
    """Spell a type the way error messages and documentation refer to it."""
    match datatype:
        case ColumnType():
            return datatype.value
        case ArrayType():
            return f"array<{type_name(datatype.element)}>"
        case MapType():
            return f"map<string,{type_name(datatype.value)}>"
        case StructType():
            return "struct"
    return "json"


def parse_type(spec: Any, aliases: AliasTable, context: str) -> DataType:
    """Build a type from its JSON spelling: a name, or a single-key object."""
    if isinstance(spec, str):
        return _named_type(spec, aliases, context)
    if isinstance(spec, dict) and len(spec) == 1:
        ((kind, body),) = spec.items()
        builder = _NESTED.get(aliases.resolve(kind))
        if builder is not None:
            return builder(body, aliases, context)
    raise SchemaError(
        f"{context}: expected a type name or a nested type such as "
        f'{{"array": {{"element": "int"}}}}, got {spec!r}'
    )


def _named_type(spec: str, aliases: AliasTable, context: str) -> DataType:
    """Resolve a bare type name; ``struct`` without fields is the ``json`` type."""
    resolved = aliases.resolve(spec)
    if resolved in _PRIMITIVE_NAMES:
        return ColumnType(resolved)
    if resolved == "struct":
        return JSON
    if resolved in _NESTED:
        raise SchemaError(
            f"{context}: type {spec!r} needs a definition, as in "
            f'{{"{resolved}": ...}}'
        )
    raise SchemaError(
        f"{context}: unknown type {spec!r}; valid types are "
        f"{', '.join(sorted(_PRIMITIVE_NAMES))}, struct, array, map, json"
    )


def _struct_type(body: Any, aliases: AliasTable, context: str) -> StructType:
    definitions = body.get("fields") if isinstance(body, dict) else None
    if not isinstance(definitions, list) or not definitions:
        raise SchemaError(f"{context}: a struct needs a non-empty 'fields' array")
    fields = tuple(_struct_field(definition, aliases, context) for definition in definitions)
    names = [field.name for field in fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SchemaError(f"{context}: duplicate struct field(s) {', '.join(duplicates)}")
    return StructType(fields)


def _struct_field(definition: Any, aliases: AliasTable, context: str) -> StructField:
    if not isinstance(definition, dict) or "name" not in definition or "type" not in definition:
        raise SchemaError(
            f"{context}: every struct field needs a 'name' and a 'type', got {definition!r}"
        )
    name = str(definition["name"])
    return StructField(name, parse_type(definition["type"], aliases, f"{context}.{name}"))


def _array_type(body: Any, aliases: AliasTable, context: str) -> ArrayType:
    if not isinstance(body, dict) or "element" not in body:
        raise SchemaError(f"{context}: an array needs an 'element' type")
    return ArrayType(parse_type(body["element"], aliases, f"{context}[]"))


def _map_type(body: Any, aliases: AliasTable, context: str) -> MapType:
    if not isinstance(body, dict) or "value" not in body:
        raise SchemaError(f"{context}: a map needs a 'value' type")
    key = body.get("key", "string")
    if not isinstance(key, str) or aliases.resolve(key) != ColumnType.STRING.value:
        raise SchemaError(f"{context}: map keys must be strings, got {key!r}")
    return MapType(parse_type(body["value"], aliases, f"{context}{{}}"))


#: The nested kinds, keyed by the canonical name their schema object uses.
_NESTED: dict[str, Callable[[Any, AliasTable, str], DataType]] = {
    "struct": _struct_type,
    "array": _array_type,
    "map": _map_type,
}

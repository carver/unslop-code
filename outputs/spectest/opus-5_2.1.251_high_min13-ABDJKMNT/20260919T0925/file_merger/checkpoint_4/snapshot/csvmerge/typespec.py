"""The type a column, struct field, array element or map value is declared to hold.

A declaration is either a primitive name, the special `json` type, or one of the
three nested kinds. Both spellings are accepted everywhere: the JSON object form the
spec documents (`{"array": {"element": ...}}`) and the generic text form the aliases
imply (`list<int>`, `map<string,int>`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .aliases import split_arguments
from .coltypes import STRING, VALID_TYPES
from .errors import SchemaError

STRUCT, ARRAY, MAP = "struct", "array", "map"


@dataclass(frozen=True)
class Primitive:
    """One of `string`, `int`, `float`, `bool`, `date`, `timestamp`."""

    name: str

    @property
    def label(self):
        return self.name


@dataclass(frozen=True)
class Field:
    """One named member of a struct."""

    name: str
    type: object


@dataclass(frozen=True)
class Struct:
    """An ordered list of named fields with unique names."""

    fields: tuple[Field, ...]

    @property
    def label(self):
        return STRUCT


@dataclass(frozen=True)
class Array:
    """A homogeneous sequence of `element`."""

    element: object

    @property
    def label(self):
        return f"array<{self.element.label}>"


@dataclass(frozen=True)
class Map:
    """A mapping from string keys onto `value`."""

    value: object

    @property
    def label(self):
        return f"map<string,{self.value.label}>"


@dataclass(frozen=True)
class AnyJson:
    """The `json` type: any JSON value, normalized but never cast."""

    @property
    def label(self):
        return "json"


#: `json` carries no parameters, so one instance serves every declaration.
JSON = AnyJson()


def parse_type(declaration, aliases):
    """Build the type `declaration` describes, resolving alias names as it goes."""
    if isinstance(declaration, dict):
        return _parse_object(declaration, aliases)
    if isinstance(declaration, str):
        return _parse_text(declaration, aliases)
    raise SchemaError(f"invalid type declaration {declaration!r}")


def _parse_text(declaration, aliases):
    """Build a type from a name, optionally with `<...>` arguments."""
    head, arguments = aliases.resolve(declaration)
    if arguments is None:
        return _parse_name(head, declaration)
    parts = split_arguments(arguments)
    if head == ARRAY and len(parts) == 1:
        return Array(parse_type(parts[0], aliases))
    if head == MAP and len(parts) == 2:
        return Map(_parse_map_value(parts[0], parts[1], aliases))
    raise SchemaError(f"invalid type declaration {declaration!r}")


def _parse_name(head, declaration):
    if head in VALID_TYPES:
        return Primitive(head)
    if head == STRUCT:
        # Reached by the built-in `json` alias: a struct with no declared fields is
        # the "accept any JSON" type (AMBIGUITIES T52).
        return JSON
    raise SchemaError(f"unknown type {declaration!r}")


def _parse_object(declaration, aliases):
    """Build a type from the `{"struct": ...}` / `{"array": ...}` / `{"map": ...}` form."""
    if len(declaration) != 1:
        raise SchemaError(f"invalid type declaration {declaration!r}")
    (kind, body), = declaration.items()
    body = body if isinstance(body, dict) else {}
    if kind == STRUCT and isinstance(body.get("fields"), list):
        return _parse_struct(body["fields"], aliases)
    if kind == ARRAY and "element" in body:
        return Array(parse_type(body["element"], aliases))
    if kind == MAP and "value" in body:
        return Map(_parse_map_value(body.get("key", STRING), body["value"], aliases))
    raise SchemaError(f"invalid type declaration {declaration!r}")


def _parse_struct(entries, aliases):
    fields = tuple(_parse_field(entry, aliases) for entry in entries)
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise SchemaError(f"struct field names must be unique: {names}")
    return Struct(fields)


def _parse_field(entry, aliases):
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise SchemaError(f"invalid struct field {entry!r}")
    return Field(entry["name"], parse_type(entry.get("type"), aliases))


def _parse_map_value(key, value, aliases):
    """Check the declared key type, which may only be `string`, and parse the value."""
    if parse_type(key, aliases) != Primitive(STRING):
        raise SchemaError(f"map keys must be strings, not {key!r}")
    return parse_type(value, aliases)

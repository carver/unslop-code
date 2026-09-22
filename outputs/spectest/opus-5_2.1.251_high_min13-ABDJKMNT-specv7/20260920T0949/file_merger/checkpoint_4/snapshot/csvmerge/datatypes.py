"""The type a column, or a field inside one, is declared with.

A declared type is one of five shapes: a :class:`Primitive` wrapping one of the
six scalar types, a :class:`Struct` of named fields, an :class:`Array`, a
:class:`Mapping` keyed by strings, or :data:`ANY_JSON` - the wildcard a field
declared ``json`` gets, which accepts whatever JSON the input holds.

Types are written either as an object (``{"array": {"element": "int"}}``) or as
text (``array<int>``, ``int``, ``json``); both go through the alias table first.
"""

from __future__ import annotations

from dataclasses import dataclass

from .aliases import Aliases
from .casting import TYPES, TypeSpec
from .errors import ToolError


@dataclass(frozen=True)
class Primitive:
    """One of the six scalar types: the leaf of every path and sort key."""

    spec: TypeSpec

    @property
    def label(self) -> str:
        return self.spec.name


@dataclass(frozen=True)
class Struct:
    """An ordered list of named fields; output keeps the declared order."""

    fields: tuple[tuple[str, "DataType"], ...]

    @property
    def label(self) -> str:
        return "struct"

    def field(self, name: str):
        """The declared type of ``name``, or ``None`` when it is not a field."""
        return dict(self.fields).get(name)


@dataclass(frozen=True)
class Array:
    """A homogeneous sequence; indices into it address its elements."""

    element: "DataType"

    @property
    def label(self) -> str:
        return f"array<{self.element.label}>"


@dataclass(frozen=True)
class Mapping:
    """A string-keyed map; output sorts its keys lexicographically."""

    value: "DataType"

    @property
    def label(self) -> str:
        return f"map<string,{self.value.label}>"


@dataclass(frozen=True)
class AnyJson:
    """The ``json`` type: any JSON value, normalised but never cast."""

    @property
    def label(self) -> str:
        return "json"


ANY_JSON = AnyJson()

DataType = Primitive | Struct | Array | Mapping | AnyJson


def parse_type(declaration, aliases: Aliases, where: str) -> DataType:
    """Build the type one schema declaration describes.

    ``where`` names the column or field being declared, so that a bad
    declaration deep inside a struct still reports where it sits.
    """
    if isinstance(declaration, str):
        return _from_text(declaration, aliases, where)
    if isinstance(declaration, dict) and len(declaration) == 1:
        (kind, body), = declaration.items()
        return _from_object(aliases.resolve(kind), body, aliases, where)
    raise ToolError(f"{where}: expected a type name or a single-key type object")


def _from_text(text: str, aliases: Aliases, where: str) -> DataType:
    """Read a type written as text: ``int``, ``json``, ``array<int>``, ..."""
    head, arguments = _split_generic(text, where)
    resolved = aliases.resolve(head)
    if arguments is None:
        if resolved in TYPES:
            return Primitive(TYPES[resolved])
        if resolved == "struct":
            return ANY_JSON  # `json`, or a struct with no declared fields
        if resolved != head:
            return _from_text(resolved, aliases, where)
        raise ToolError(f"{where}: unknown type {text!r}")
    return _generic(resolved, arguments, aliases, where, text)


def _split_generic(text: str, where: str) -> tuple[str, list[str] | None]:
    """Split ``name<a,b>`` into its head and arguments; plain names get ``None``."""
    stripped = text.strip()
    if "<" not in stripped:
        return stripped, None
    if not stripped.endswith(">"):
        raise ToolError(f"{where}: unbalanced type parameters in {text!r}")
    head, _, inside = stripped.partition("<")
    return head.strip(), _split_arguments(inside[:-1], where, text)


def _split_arguments(inside: str, where: str, text: str) -> list[str]:
    """Split a parameter list on its top level commas."""
    arguments, depth, start = [], 0, 0
    for position, char in enumerate(inside):
        depth += (char == "<") - (char == ">")
        if char == "," and depth == 0:
            arguments.append(inside[start:position])
            start = position + 1
    if depth:
        raise ToolError(f"{where}: unbalanced type parameters in {text!r}")
    return arguments + [inside[start:]]


def _generic(kind: str, arguments: list[str], aliases: Aliases, where: str, text: str) -> DataType:
    """Build ``array<T>`` or ``map<string,T>`` from its textual parameters."""
    if kind == "array" and len(arguments) == 1:
        return Array(_from_text(arguments[0], aliases, where))
    if kind == "map" and len(arguments) == 2:
        _check_key_type(arguments[0], aliases, where)
        return Mapping(_from_text(arguments[1], aliases, where))
    raise ToolError(f"{where}: unsupported type {text!r}")


def _from_object(kind: str, body, aliases: Aliases, where: str) -> DataType:
    """Build a type from its object form, whose body describes the kind."""
    if not isinstance(body, dict):
        raise ToolError(f"{where}: the body of a {kind!r} type must be an object")
    if kind == "struct":
        return _struct(body, aliases, where)
    if kind == "array":
        return Array(parse_type(body.get("element"), aliases, f"{where} element"))
    if kind == "map":
        _check_key_type(body.get("key", "string"), aliases, where)
        return Mapping(parse_type(body.get("value"), aliases, f"{where} value"))
    raise ToolError(f"{where}: unknown type {kind!r}")


def _struct(body: dict, aliases: Aliases, where: str) -> Struct:
    """Read a struct's ordered fields, rejecting a repeated field name."""
    declarations = body.get("fields")
    if not isinstance(declarations, list):
        raise ToolError(f"{where}: a struct needs a 'fields' list")

    fields = []
    for declaration in declarations:
        if not isinstance(declaration, dict) or not isinstance(declaration.get("name"), str):
            raise ToolError(f"{where}: every struct field needs a string 'name'")
        name = declaration["name"]
        if any(name == existing for existing, _ in fields):
            raise ToolError(f"{where}: duplicate struct field name {name!r}")
        fields.append((name, parse_type(declaration.get("type"), aliases, f"{where}.{name}")))
    return Struct(tuple(fields))


def _check_key_type(declaration, aliases: Aliases, where: str) -> None:
    """A map's keys are strings; anything else makes the declaration invalid."""
    if not isinstance(declaration, str) or aliases.resolve(declaration) != "string":
        raise ToolError(f"{where}: map keys must be strings, not {declaration!r}")

"""Reading a declared type: its two spellings, and the aliases accepted for it.

A type is written either as text — ``int``, ``array<int>``,
``map<string,array<int>>`` — or as a single-key object when it needs more than
a name, as a struct does::

    {"struct": {"fields": [{"name": "sku", "type": "string"}]}}
    {"array": {"element": "int"}}
    {"map": {"key": "string", "value": "int"}}

Any name may be an alias: names are lowercased and then followed through the
alias table until they reach a type this module can build.
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any

from .datatypes import JSON, ArrayType, DataType, Field, MapType, StructType
from .errors import AliasError, SchemaError
from .types import ColumnType

#: Aliases every run accepts. ``json`` is the interesting one: it resolves to a
#: ``struct`` with no declared fields, which is the type that takes any JSON.
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

_PRIMITIVES = {column_type.value: column_type for column_type in ColumnType}

#: The names and the punctuation of a text type such as ``map<string,int>``.
_TOKENS = re.compile(r"[<>,]|[^<>,\s]+")
_PUNCTUATION = frozenset("<>,")


def load_aliases(path: str | None) -> dict[str, str]:
    """Return the alias table: the built-ins, plus ``{"aliases": {...}}`` from ``path``.

    A file's entries are layered over the built-ins, so it may extend them or
    respell one of them. Aliases may point at other aliases; a chain that comes
    back to where it started is rejected here rather than when it is used.
    """
    aliases = {**BUILTIN_ALIASES, **_read_aliases(path)}
    _check_cycles(aliases)
    return aliases


def parse_type(spec: Any, aliases: dict[str, str]) -> DataType:
    """Parse one declared type, in either the text or the object spelling."""
    if isinstance(spec, str):
        return _parse_text(spec, aliases)
    if isinstance(spec, dict) and len(spec) == 1:
        (name, body), = spec.items()
        return _parse_object(name, body, aliases)
    raise SchemaError(f"a type must be a name or a single-key object, found {spec!r}")


def _read_aliases(path: str | None) -> dict[str, str]:
    if path is None:
        return {}
    with open(path, encoding="utf-8") as stream:
        try:
            document = json.load(stream)
        except json.JSONDecodeError as error:
            raise AliasError(f"{path}: invalid JSON ({error})") from error
    entries = document.get("aliases")
    if not isinstance(entries, dict):
        raise AliasError(f"{path}: alias file must contain an 'aliases' object")
    for name, target in entries.items():
        if not isinstance(target, str) or not target.strip():
            raise AliasError(f"{path}: alias {name!r} must name a type")
    return {name.strip().lower(): target.strip().lower() for name, target in entries.items()}


def _check_cycles(aliases: dict[str, str]) -> None:
    """Reject an alias that reaches, however indirectly, back to itself."""
    for name in aliases:
        pending = deque(_referenced(aliases[name]))
        seen = set()
        while pending:
            current = pending.popleft()
            if current == name:
                raise AliasError(f"type alias {name!r} resolves in a cycle")
            if current in seen or current not in aliases:
                continue
            seen.add(current)
            pending.extend(_referenced(aliases[current]))


def _referenced(expression: str) -> list[str]:
    return [token.lower() for token in _TOKENS.findall(expression) if token not in _PUNCTUATION]


def _parse_text(text: str, aliases: dict[str, str]) -> DataType:
    tokens = deque(_TOKENS.findall(text))
    if not tokens:
        raise SchemaError("a type cannot be empty")
    data_type = _parse_expression(tokens, aliases)
    if tokens:
        raise SchemaError(f"unexpected {tokens[0]!r} in type {text!r}")
    return data_type


def _parse_expression(tokens: deque[str], aliases: dict[str, str]) -> DataType:
    name = tokens.popleft()
    if name in _PUNCTUATION:
        raise SchemaError(f"expected a type name, found {name!r}")
    return _build(name, _parse_arguments(tokens, aliases), aliases)


def _parse_arguments(tokens: deque[str], aliases: dict[str, str]) -> tuple[DataType, ...]:
    """Parse the ``<...>`` following a name, which may be absent."""
    if not tokens or tokens[0] != "<":
        return ()
    tokens.popleft()
    arguments = [_parse_expression(tokens, aliases)]
    while tokens and tokens[0] == ",":
        tokens.popleft()
        arguments.append(_parse_expression(tokens, aliases))
    if not tokens or tokens.popleft() != ">":
        raise SchemaError("unbalanced '<' in a type")
    return tuple(arguments)


def _build(name: str, arguments: tuple[DataType, ...], aliases: dict[str, str]) -> DataType:
    key = _expand(name, aliases)
    builder = _BUILDERS.get(key)
    if builder is not None:
        return builder(key, arguments)
    target = aliases.get(key)
    if target is None:
        raise SchemaError(f"unknown type {name!r} (expected one of: {_SUPPORTED})")
    if arguments:
        raise SchemaError(f"type alias {name!r} takes no type arguments")
    return _parse_text(target, aliases)


def _expand(name: str, aliases: dict[str, str]) -> str:
    """Follow the aliases that merely rename a type down to the name they spell.

    An alias standing for a whole type, such as ``ids`` for ``array<int>``, ends
    the walk: its target is an expression rather than a name.
    """
    key = name.strip().lower()
    for _step in range(len(aliases) + 1):
        target = aliases.get(key)
        if key in _BUILDERS or target is None or "<" in target:
            return key
        key = target
    raise AliasError(f"type alias {name!r} resolves in a cycle")


def _parse_object(name: str, body: Any, aliases: dict[str, str]) -> DataType:
    builder = _OBJECT_BUILDERS.get(_expand(name, aliases))
    if builder is None:
        raise SchemaError(f"type {name!r} cannot be declared as an object")
    if not isinstance(body, dict):
        raise SchemaError(f"type {name!r} must be described by an object, found {body!r}")
    return builder(body, aliases)


def _build_primitive(key: str, arguments: tuple[DataType, ...]) -> DataType:
    _reject_arguments(key, arguments)
    return _PRIMITIVES[key]


def _build_struct(key: str, arguments: tuple[DataType, ...]) -> DataType:
    """Build a bare ``struct`` — the ``json`` alias — which takes any JSON value.

    A struct with declared fields can only be written in the object spelling.
    """
    _reject_arguments(key, arguments)
    return JSON


def _build_array(key: str, arguments: tuple[DataType, ...]) -> DataType:
    if len(arguments) != 1:
        raise SchemaError(f"{key} needs exactly one element type, as in array<int>")
    return ArrayType(arguments[0])


def _build_map(key: str, arguments: tuple[DataType, ...]) -> DataType:
    if len(arguments) != 2:
        raise SchemaError(f"{key} needs a key and a value type, as in map<string,int>")
    _require_string_key(arguments[0])
    return MapType(arguments[1])


def _struct_from(body: dict, aliases: dict[str, str]) -> DataType:
    entries = body.get("fields")
    if not isinstance(entries, list):
        raise SchemaError("a struct needs a 'fields' list")
    fields = tuple(_parse_field(entry, aliases) for entry in entries)
    names = [field.name for field in fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SchemaError(f"struct field(s) declared twice: {', '.join(duplicates)}")
    return StructType(fields)


def _array_from(body: dict, aliases: dict[str, str]) -> DataType:
    if "element" not in body:
        raise SchemaError("an array needs an 'element' type")
    return ArrayType(parse_type(body["element"], aliases))


def _map_from(body: dict, aliases: dict[str, str]) -> DataType:
    if "value" not in body:
        raise SchemaError("a map needs a 'value' type")
    _require_string_key(parse_type(body.get("key", "string"), aliases))
    return MapType(parse_type(body["value"], aliases))


def _parse_field(entry: Any, aliases: dict[str, str]) -> Field:
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or "type" not in entry:
        raise SchemaError("every struct field needs a 'name' and a 'type'")
    return Field(entry["name"], parse_type(entry["type"], aliases))


def _require_string_key(data_type: DataType) -> None:
    if data_type is not ColumnType.STRING:
        raise SchemaError("a map must be keyed by string")


def _reject_arguments(key: str, arguments: tuple[DataType, ...]) -> None:
    if arguments:
        raise SchemaError(f"type {key} takes no type arguments")


_BUILDERS = {
    **{name: _build_primitive for name in _PRIMITIVES},
    "struct": _build_struct,
    "array": _build_array,
    "map": _build_map,
}

_OBJECT_BUILDERS = {"struct": _struct_from, "array": _array_from, "map": _map_from}

_SUPPORTED = ", ".join([*_PRIMITIVES, "struct", "array<T>", "map<string,T>", "json"])

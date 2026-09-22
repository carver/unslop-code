"""Casting a column's value, nested types included, and spelling it for output.

A cast column is a tree: a :class:`~csvmerge.casting.Cell` at every primitive
leaf, a ``dict`` for a struct (in declared field order) or a map (with its keys
sorted), a ``list`` for an array, and a :class:`RawJson` wrapper for a ``json``
column, whose value is carried through uncast. A primitive column is simply a
tree of one cell, so :func:`cast_column` and :func:`format_column` are the only
entry points a row needs.

Nested columns are written as canonical JSON: minified, UTF-8, structs in
schema order, map and object keys sorted, arrays left in their original order.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from operator import itemgetter
from typing import Any, Union

from .casting import NULL_CELL, CastContext, Cell, cast_cell, format_cell, on_failure
from .datatypes import ArrayType, DataType, JsonType, MapType, StructType, is_primitive
from .types import JSON_SCALARS, as_text


@dataclass(frozen=True)
class RawJson:
    """A ``json`` column's value: any JSON at all, normalised but never cast."""

    value: Any


Node = Union[Cell, list, dict, RawJson]

#: Stands in for text that was meant to be a JSON literal and was not.
_INVALID = object()


def cast_column(value: Any, data_type: DataType, path: str, context: CastContext) -> Node:
    """Cast one input value into ``data_type``, descending through nested types.

    ``path`` names the field being cast — ``user.prefs.theme``, ``items.0.qty``
    — and appears in the message a rejected cast raises.
    """
    if is_primitive(data_type):
        return cast_cell(_flatten(value), data_type, path, context)
    if value is None:
        return NULL_CELL
    decoded = _decode(value, context)
    if decoded is _INVALID:
        return on_failure(value, data_type, path, context)  # the original text, not a structure
    return _CASTERS[type(data_type)](decoded, data_type, path, context)


def format_column(node: Node, null_literal: str) -> str:
    """Render a cast column as one CSV cell: a null, a scalar, or canonical JSON."""
    if isinstance(node, Cell):
        return format_cell(node, null_literal)
    return json_text(node)


def json_text(node: Node) -> str:
    """Serialise a cast node as canonical JSON: minified, UTF-8, RFC 8259 escapes."""
    return json.dumps(_plain(node), separators=(",", ":"), ensure_ascii=False)


def _decode(value: Any, context: CastContext) -> Any:
    """Read the single JSON literal a text source spells a nested value with.

    Only CSV and TSV need this: the other formats hand over values that are
    already structured, and a ``json`` column there may well hold a bare string.
    """
    if not (context.parse_text and isinstance(value, str)):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return _INVALID


def _flatten(value: Any) -> Any:
    """Spell a structure as JSON text, which is how a failed cast has to keep it.

    Only a ``string`` column can hold one; every other primitive rejects the
    text and falls to ``--on-type-error``, as it would for any other bad value.
    """
    if isinstance(value, (dict, list)):
        return json_text(RawJson(value))
    return value


def _failed(value: Any, data_type: DataType, path: str, context: CastContext) -> Cell:
    """Hand a value that does not fit its nested type to ``--on-type-error``."""
    return on_failure(_flatten(value), data_type, path, context)


def _cast_struct(value: Any, data_type: StructType, path: str, context: CastContext) -> Node:
    if not isinstance(value, dict):
        return _failed(value, data_type, path, context)
    return {
        field.name: cast_column(value.get(field.name), field.type, f"{path}.{field.name}", context)
        for field in data_type.fields
    }


def _cast_array(value: Any, data_type: ArrayType, path: str, context: CastContext) -> Node:
    if not isinstance(value, list):
        return _failed(value, data_type, path, context)
    return [
        cast_column(item, data_type.element, f"{path}.{index}", context)
        for index, item in enumerate(value)
    ]


def _cast_map(value: Any, data_type: MapType, path: str, context: CastContext) -> Node:
    """Cast a map, accepting both an object and the key/value pairs Arrow yields."""
    entries = _entries(value)
    if entries is None:
        return _failed(value, data_type, path, context)
    return {
        key: cast_column(item, data_type.value, f"{path}.{key}", context)
        for key, item in sorted(((as_text(key), item) for key, item in entries), key=itemgetter(0))
    }


def _cast_json(value: Any, _data_type: JsonType, _path: str, _context: CastContext) -> Node:
    return RawJson(value)


def _entries(value: Any) -> Iterable[tuple[Any, Any]] | None:
    if isinstance(value, dict):
        return value.items()
    if isinstance(value, list) and all(isinstance(entry, (list, tuple)) and len(entry) == 2 for entry in value):
        return value
    return None


_CASTERS = {
    StructType: _cast_struct,
    ArrayType: _cast_array,
    MapType: _cast_map,
    JsonType: _cast_json,
}


def _plain_cell(cell: Cell) -> Any:
    if cell.value is None:
        return None
    return JSON_SCALARS[cell.kind](cell.value)


def _normalise(value: Any) -> Any:
    """Spell an uncast JSON value canonically: object keys sorted, scalars as text."""
    if isinstance(value, dict):
        pairs = sorted(((as_text(key), item) for key, item in value.items()), key=itemgetter(0))
        return {key: _normalise(item) for key, item in pairs}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return as_text(value)


_PLAIN = {
    Cell: _plain_cell,
    RawJson: lambda node: _normalise(node.value),
    dict: lambda node: {key: _plain(item) for key, item in node.items()},
    list: lambda node: [_plain(item) for item in node],
}


def _plain(node: Node) -> Any:
    return _PLAIN[type(node)](node)

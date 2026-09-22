"""Casting a raw input row onto the declared schema, nesting included.

A value is cast to the type its column declares: primitives through
:mod:`csvmerge.coltypes`, nested types by recursing into their members.  Every
failure is handled where it happens — a bad element inside an array only
affects that element — so ``--on-type-error`` applies per field rather than per
row.  The result is a tree of Python values in canonical order, which
``render_cell`` turns into the text the CSV carries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from operator import itemgetter
from typing import Any, Callable, Sequence

from .coltypes import CastError, ColumnType, cast_value, format_value
from .datatypes import (
    ArrayType,
    DataType,
    JsonType,
    MapType,
    StructType,
    is_primitive,
    type_name,
)
from .errors import TypeCastError
from .schema import Column


class TypeErrorPolicy(str, Enum):
    """What to do with a cell that does not fit its column's type."""

    COERCE_NULL = "coerce-null"
    FAIL = "fail"
    KEEP_STRING = "keep-string"


@dataclass(frozen=True)
class CastContext:
    """The policy in force, the row it applies to and how that row spells JSON.

    ``text_cells`` marks the delimited formats, whose nested cells hold a JSON
    literal to be parsed; JSON Lines and Parquet hand over values that already
    are objects, lists and scalars.
    """

    policy: TypeErrorPolicy
    file: str
    line: int
    text_cells: bool = False


def cast_row(
    row: dict[str, Any], columns: Sequence[Column], context: CastContext
) -> list[Any]:
    """Cast one raw row into schema order.

    Columns the file does not provide, cells holding the null literal and typed
    nulls all stay ``None`` and are written out as the null literal.
    """
    return [
        cast_field(row.get(column.name), column.type, column.name, context)
        for column in columns
    ]


def cast_field(value: Any, datatype: DataType, path: str, context: CastContext) -> Any:
    """Cast one value to ``datatype``, recovering per ``--on-type-error``."""
    if value is None:
        return None
    try:
        return _CASTERS[type(datatype)](value, datatype, path, context)
    except CastError as error:
        return _recover(value, datatype, path, context, error)


def render_cell(value: Any, datatype: DataType) -> str | None:
    """Render a cast column value as the text its CSV cell carries."""
    if value is None:
        return None
    if is_primitive(datatype):
        return format_value(value)
    return canonical_json(value)


def canonical_json(tree: Any) -> str:
    """Serialise a cast tree as minified JSON.

    Ordering is already settled by the cast — struct fields in declared order,
    map and ``json`` object keys lexicographically — so only the temporal types
    still need spelling out, which ``format_value`` does.
    """
    return json.dumps(
        tree, ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=format_value
    )


def stringify(value: Any) -> str:
    """Spell a value as text, as ``--on-type-error keep-string`` leaves it."""
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return format_value(value)


def _recover(
    value: Any, datatype: DataType, path: str, context: CastContext, error: CastError
) -> Any:
    if context.policy is TypeErrorPolicy.FAIL:
        raise TypeCastError(
            f'cannot cast "{stringify(value)}" to {type_name(datatype)} in field "{path}" '
            f"(file={context.file} line={context.line})"
        ) from error
    return stringify(value) if context.policy is TypeErrorPolicy.KEEP_STRING else None


def _cast_primitive(value: Any, datatype: ColumnType, path: str, context: CastContext) -> Any:
    return cast_value(value, datatype)


def _cast_json(value: Any, datatype: JsonType, path: str, context: CastContext) -> Any:
    """Accept any JSON value as it is, normalising object key order only."""
    return _normalise(_literal(value, context))


def _cast_struct(value: Any, datatype: StructType, path: str, context: CastContext) -> dict:
    """Cast every declared field, in declared order; absent ones become null."""
    members = _shaped(value, dict, datatype, context)
    return {
        field.name: cast_field(
            members.get(field.name), field.type, f"{path}.{field.name}", context
        )
        for field in datatype.fields
    }


def _cast_array(value: Any, datatype: ArrayType, path: str, context: CastContext) -> list:
    return [
        cast_field(item, datatype.element, f"{path}.{index}", context)
        for index, item in enumerate(_shaped(value, list, datatype, context))
    ]


def _cast_map(value: Any, datatype: MapType, path: str, context: CastContext) -> dict:
    """Cast every entry, keyed by its string key and ordered lexicographically."""
    return {
        key: cast_field(item, datatype.value, f"{path}[{json.dumps(key)}]", context)
        for key, item in _entries(_shaped(value, dict, datatype, context))
    }


#: One caster per kind of declared type, keyed by the type's class.
_CASTERS: dict[type, Callable[[Any, Any, str, CastContext], Any]] = {
    ColumnType: _cast_primitive,
    JsonType: _cast_json,
    StructType: _cast_struct,
    ArrayType: _cast_array,
    MapType: _cast_map,
}


def _literal(value: Any, context: CastContext) -> Any:
    """Read the single JSON literal a delimited cell holds, if it is one."""
    if not context.text_cells or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError as error:
        raise CastError(f"{value!r} is not a JSON literal") from error


def _shaped(value: Any, kind: type, datatype: DataType, context: CastContext) -> Any:
    """Decode a nested value from text if needed and check its JSON shape."""
    decoded = _literal(value, context)
    if not isinstance(decoded, kind):
        raise CastError(f"{decoded!r} does not have the shape of a {type_name(datatype)}")
    return decoded


def _entries(mapping: dict) -> list[tuple[str, Any]]:
    """A mapping's entries, keyed by text and ordered lexicographically."""
    return sorted(
        (
            (key if isinstance(key, str) else format_value(key), value)
            for key, value in mapping.items()
        ),
        key=itemgetter(0),
    )


def _normalise(value: Any) -> Any:
    """Put every object inside a ``json`` value into lexicographic key order."""
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in _entries(value)}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    return value

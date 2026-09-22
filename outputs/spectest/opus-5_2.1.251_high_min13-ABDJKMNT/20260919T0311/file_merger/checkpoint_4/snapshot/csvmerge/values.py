"""Casting one row's values to their declared types and rendering them as cells.

A cell carries both the text the CSV output holds and the value `--key` and
`--partition-by` paths traverse: a JSON-ready tree for a nested column, and the
cast leaf for a primitive one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .casting import cast, cast_leaf, to_text
from .errors import EXIT_CAST, MergeError
from .schema import Column
from .types import Array, Map, Struct, TypeExpr, describe, is_primitive

#: Rank prefixes that order nulls before every value, and text kept by
#: `--on-type-error keep-string` after every well-typed value.
NULL_RANK, VALUE_RANK, RAW_RANK = 0, 1, 2

#: Placeholder paired with NULL_RANK so that key parts stay comparable.
_NULL_SORT_VALUE = ""

#: JSON numbers above this magnitude stay floats rather than becoming ints.
_INT64_LIMIT = 2 ** 63


@dataclass(frozen=True)
class CastPolicy:
    """How cells become output text: what counts as null, and what a bad cast does."""

    on_error: str
    null_literal: str

    def is_null(self, text: str | None) -> bool:
        """A missing cell, an empty cell, or one spelled as the null literal."""
        return text is None or text == "" or text == self.null_literal


@dataclass(frozen=True)
class Cell:
    """One output cell: its CSV text, and the value field paths read."""

    text: str
    value: Any


def canonical_json(value: Any) -> str:
    """The one JSON spelling of a cast nested value: minified, UTF-8, ordered.

    Ordering is already baked into the value: struct fields arrive in schema
    order and map keys sorted, both of which `json.dumps` preserves.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json(text: str) -> Any:
    """Parse a text cell that must hold a single JSON literal."""
    try:
        return prefer_ints(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from None


def prefer_ints(value: Any) -> Any:
    """Read JSON numbers as ints wherever they are integral, at any depth."""
    if isinstance(value, dict):
        return {key: prefer_ints(item) for key, item in value.items()}
    if isinstance(value, list):
        return [prefer_ints(item) for item in value]
    if type(value) is float and value.is_integer() and abs(value) < _INT64_LIMIT:
        return int(value)
    return value


def leaf_fragment(value: Any, type_name: str) -> tuple[str | None, list]:
    """The partition text and sort key part of one primitive value.

    A value that does not parse is one `--on-type-error keep-string` kept, and
    it sorts after every well-typed value of the column.
    """
    if value is None:
        return None, [NULL_RANK, _NULL_SORT_VALUE]
    text = to_text(value)
    try:
        rendered, sort_value = cast(text, type_name)
    except ValueError:
        return text, [RAW_RANK, text]
    return rendered, [VALUE_RANK, sort_value]


class ValueCaster:
    """Casts the values of one input row, applying `--on-type-error` at any depth."""

    def __init__(self, policy: CastPolicy, typed: bool, location: str):
        self._policy = policy
        self._typed = typed
        self._location = location

    def cell(self, raw: Any, column: Column) -> Cell:
        """The output cell for one column of one row."""
        if raw is None or (not self._typed and self._policy.is_null(raw)):
            return Cell(self._policy.null_literal, None)
        if is_primitive(column.type):
            value = self._value(raw, column.type, column.name)
            return Cell(self._policy.null_literal if value is None else to_text(value), value)
        return self._nested_cell(raw, column)

    def _nested_cell(self, raw: Any, column: Column) -> Cell:
        """A nested or `json` column, whose cell is the value's canonical JSON."""
        if not self._typed:
            try:
                raw = load_json(raw)
            except ValueError:
                # Text that is not JSON at all has no JSON form to keep, so
                # `keep-string` keeps the cell exactly as it arrived.
                if self._policy.on_error == "keep-string":
                    return Cell(raw, raw)
                raw = self._failed(raw, column.type, column.name)
        return self._json_cell(self._value(raw, column.type, column.name))

    def _json_cell(self, value: Any) -> Cell:
        return Cell(self._policy.null_literal if value is None else canonical_json(value),
                    value)

    def _value(self, raw: Any, type_expr: TypeExpr, path: str) -> Any:
        """`raw` cast to `type_expr`, as a JSON-ready value."""
        if raw is None:
            return None
        if is_primitive(type_expr):
            return self._leaf(raw, type_expr, path)
        if isinstance(type_expr, Struct):
            return self._struct(raw, type_expr, path)
        if isinstance(type_expr, Array):
            return self._array(raw, type_expr, path)
        if isinstance(type_expr, Map):
            return self._map(raw, type_expr, path)
        return _normalized(raw)

    def _leaf(self, raw: Any, type_name: str, path: str) -> Any:
        if isinstance(raw, (dict, list)):
            return self._failed(raw, type_name, path)
        try:
            return cast_leaf(to_text(raw), type_name)
        except ValueError:
            return self._failed(raw, type_name, path)

    def _struct(self, raw: Any, struct: Struct, path: str) -> Any:
        """Every declared field, in declaration order, null where the input has none."""
        if not isinstance(raw, dict):
            return self._failed(raw, struct, path)
        return {field.name: self._value(raw.get(field.name), field.type,
                                        f"{path}.{field.name}")
                for field in struct.fields}

    def _array(self, raw: Any, array: Array, path: str) -> Any:
        if not isinstance(raw, list):
            return self._failed(raw, array, path)
        return [self._value(item, array.element, f"{path}.{index}")
                for index, item in enumerate(raw)]

    def _map(self, raw: Any, map_type: Map, path: str) -> Any:
        """Entries under lexicographically sorted keys."""
        if not isinstance(raw, dict):
            return self._failed(raw, map_type, path)
        return {key: self._value(raw[key], map_type.value, f'{path}["{key}"]')
                for key in sorted(raw)}

    def _failed(self, raw: Any, type_expr: TypeExpr, path: str) -> Any:
        """Apply `--on-type-error` to a value that will not cast."""
        shown = _stringified(raw)
        if self._policy.on_error == "fail":
            raise MergeError(
                f'cannot cast "{shown}" to {describe(type_expr)} in field "{path}" '
                f"({self._location})",
                EXIT_CAST,
            )
        return shown if self._policy.on_error == "keep-string" else None


def _normalized(value: Any) -> Any:
    """A `json` value, ordered for output but otherwise untouched."""
    if isinstance(value, dict):
        return {key: _normalized(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _stringified(value: Any) -> str:
    """The text `keep-string` keeps, and the value an error message quotes."""
    if isinstance(value, (dict, list)):
        return canonical_json(_normalized(value))
    return to_text(value)

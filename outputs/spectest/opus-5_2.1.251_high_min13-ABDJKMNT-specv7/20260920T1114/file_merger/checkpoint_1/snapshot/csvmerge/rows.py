"""Turning raw input cells into output text plus a comparable sort key.

A sort key is a small JSON-friendly list so that it survives a round trip through
a spill file. Its first element ranks the cell: nulls come before every cast
value (the spec's null ordering), and text kept by ``--on-type-error keep-string``
comes after them, which keeps the key total without comparing text to numbers.
"""

from __future__ import annotations

from csvmerge.errors import MergeError
from csvmerge.reader import InputDialect
from csvmerge.schema import Column, Schema
from csvmerge.types import TYPES

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"

_NULL_RANK = 0
_VALUE_RANK = 1
_KEPT_TEXT_RANK = 2

Cell = tuple[str, list]


def convert_row(
    raw_cells: list[str],
    schema: Schema,
    dialect: InputDialect,
    policy: str,
) -> tuple[list[str], list[list]]:
    """Cast one input row into output texts and per-column sort keys."""
    converted = [
        _convert_cell(raw, column, dialect, policy)
        for raw, column in zip(raw_cells, schema.columns)
    ]
    return [text for text, _ in converted], [key for _, key in converted]


def _convert_cell(raw: str, column: Column, dialect: InputDialect, policy: str) -> Cell:
    """Cast a single cell, applying the error policy when it does not parse."""
    if dialect.is_null(raw):
        return dialect.null_literal, [_NULL_RANK]
    definition = TYPES[column.type]
    try:
        value = definition.parse(raw)
    except ValueError:
        return _on_error(raw, column, dialect, policy)
    return definition.render(value), [_VALUE_RANK, definition.sort_value(value)]


def _on_error(raw: str, column: Column, dialect: InputDialect, policy: str) -> Cell:
    if policy == FAIL:
        raise MergeError(f"cannot cast {raw!r} in column {column.name!r} to {column.type}")
    if policy == KEEP_STRING:
        return raw, [_KEPT_TEXT_RANK, raw]
    return dialect.null_literal, [_NULL_RANK]

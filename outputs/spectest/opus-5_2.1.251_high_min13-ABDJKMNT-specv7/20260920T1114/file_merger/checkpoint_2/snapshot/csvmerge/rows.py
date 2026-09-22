"""Turning one input record into output text plus a comparable sort key.

A sort key is a small JSON-friendly list so that it survives a round trip through
a spill file. Its first element ranks the cell: nulls come before every cast
value (the spec's null ordering), and text kept by ``--on-type-error keep-string``
comes after them, which keeps the key total without comparing text to numbers.
"""

from __future__ import annotations

from csvmerge.dialect import CsvDialect
from csvmerge.errors import EXIT_TYPE, MergeError
from csvmerge.schema import Column, Schema
from csvmerge.types import TYPES
from csvmerge.values import canonical_text

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"

_NULL_RANK = 0
_VALUE_RANK = 1
_KEPT_TEXT_RANK = 2

Cell = tuple[str, list]


def convert_row(
    record: dict[str, object],
    schema: Schema,
    dialect: CsvDialect,
    policy: str,
) -> tuple[list[str], list[list]]:
    """Cast one input record into output texts and per-column sort keys."""
    converted = [
        _convert_cell(record.get(column.name), column, dialect, policy)
        for column in schema.columns
    ]
    return [text for text, _ in converted], [key for _, key in converted]


def _convert_cell(
    value: object, column: Column, dialect: CsvDialect, policy: str
) -> Cell:
    """Cast a single value, applying the error policy when it does not parse.

    Values from typed sources are first spelled as text, so that one set of cast
    rules serves every input format.
    """
    if value is None:
        return dialect.null_literal, [_NULL_RANK]
    definition = TYPES[column.type]
    text = canonical_text(value)
    try:
        parsed = definition.parse(text)
    except ValueError:
        return _on_error(text, column, dialect, policy)
    return definition.render(parsed), [_VALUE_RANK, definition.sort_value(parsed)]


def _on_error(text: str, column: Column, dialect: CsvDialect, policy: str) -> Cell:
    if policy == FAIL:
        raise MergeError(
            f"cannot cast {text!r} in column {column.name!r} to {column.type}",
            EXIT_TYPE,
        )
    if policy == KEEP_STRING:
        return text, [_KEPT_TEXT_RANK, text]
    return dialect.null_literal, [_NULL_RANK]

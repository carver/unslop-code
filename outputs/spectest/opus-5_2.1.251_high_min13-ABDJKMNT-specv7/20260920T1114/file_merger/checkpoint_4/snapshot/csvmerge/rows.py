"""Turning one input record into output cells and comparable key fragments.

A key fragment is a small JSON-friendly list so that it survives a round trip
through a spill file. Its first element ranks the value: nulls come before every
cast value (the spec's null ordering), and text kept by ``--on-type-error
keep-string`` comes after them, which keeps the key total without comparing text
to numbers (ambiguity T12).
"""

from __future__ import annotations

import json
from datetime import date, datetime

from csvmerge.casting import CastContext, Kept, cast, render
from csvmerge.dialect import CsvDialect
from csvmerge.schema import Column, Schema
from csvmerge.typespec import Primitive

_NULL_RANK = 0
_VALUE_RANK = 1
_KEPT_TEXT_RANK = 2

_SORT_VALUES = {bool: int, date: date.toordinal, datetime: datetime.timestamp}


def cast_record(
    record: dict[str, object], schema: Schema, context: CastContext, from_text: bool
) -> dict[str, object]:
    """Cast every schema column of one input record to its declared type."""
    return {
        column.name: _cast_column(record.get(column.name), column, context, from_text)
        for column in schema.columns
    }


def cells_of(
    casted: dict[str, object], schema: Schema, dialect: CsvDialect
) -> list[str]:
    """The output texts of one casted record, in schema order."""
    texts = (render(casted[column.name], column.type) for column in schema.columns)
    return [dialect.null_literal if text is None else text for text in texts]


def sort_key(value: object) -> list:
    """A comparable, JSON-friendly key fragment for one casted leaf value."""
    if value is None:
        return [_NULL_RANK]
    if isinstance(value, Kept):
        return [_KEPT_TEXT_RANK, value.text]
    return [_VALUE_RANK, _SORT_VALUES.get(type(value), _unchanged)(value)]


def _cast_column(
    value: object, column: Column, context: CastContext, from_text: bool
) -> object:
    """Cast one cell; a text cell holding a nested value is decoded first.

    CSV and TSV carry nested values as a single JSON literal per cell, so the
    text is read as JSON before the declared type sees it (ambiguity T52).
    """
    if from_text and isinstance(value, str) and not isinstance(column.type, Primitive):
        try:
            value = json.loads(value)
        except ValueError:
            return context.failed(value, column.type, column.name)
    return cast(value, column.type, column.name, context)


def _unchanged(value: object) -> object:
    return value

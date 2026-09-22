"""Turning raw input rows into sortable, output-ready records."""

from __future__ import annotations

from typing import Any, Iterable, Iterator, NamedTuple, Sequence

from csvmerge.csvio import InputDialect, iter_aligned_rows
from csvmerge.errors import MergeError
from csvmerge.schema import Column, Schema
from csvmerge.values import cast, comparable, format_value

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"


class Record(NamedTuple):
    """One output row: its sort key, its arrival order, and its rendered cells."""

    key: tuple
    sequence: int
    cells: tuple[str, ...]


def build_records(
    paths: Iterable[str],
    schema: Schema,
    key_indexes: Sequence[int],
    dialect: InputDialect,
    on_type_error: str,
) -> Iterator[Record]:
    """Read every input in order, casting each row into the resolved schema.

    The sequence number counts rows across all inputs, so it preserves input
    appearance order for rows whose keys tie - including across sorted runs.
    """
    sequence = 0
    for path in paths:
        for line_number, texts in iter_aligned_rows(path, schema.names, dialect):
            values = [
                _resolve_cell(text, column, dialect, on_type_error, f"{path}:{line_number}")
                for text, column in zip(texts, schema.columns)
            ]
            yield Record(
                key=tuple(comparable(values[index]) for index in key_indexes),
                sequence=sequence,
                cells=tuple(format_value(value, dialect.null_literal) for value in values),
            )
            sequence += 1


def _resolve_cell(
    text: str | None, column: Column, dialect: InputDialect, on_type_error: str, location: str
) -> Any:
    """Cast one cell, applying the configured policy when it will not parse."""
    if dialect.is_null(text):
        return None
    parsed, value = cast(text, column.type)
    if parsed:
        return value
    if on_type_error == FAIL:
        raise MergeError(f"{location}: cannot cast {text!r} to {column.type} for column {column.name!r}")
    return text if on_type_error == KEEP_STRING else None

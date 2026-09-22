"""Turning raw input rows into sortable, output-ready records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, NamedTuple, Sequence

from csvmerge.errors import MergeError
from csvmerge.partition import partition_path
from csvmerge.schema import Column, Schema
from csvmerge.sources import Source
from csvmerge.values import cast_value, comparable, format_value

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"


class Record(NamedTuple):
    """One output row: where it belongs, how it sorts, and its rendered cells.

    ``partition`` is the relative directory the row is written under, empty
    when ``--partition-by`` was not given.
    """

    partition: str
    key: tuple
    sequence: int
    cells: tuple[str, ...]


@dataclass(frozen=True)
class RecordPlan:
    """Everything that shapes an output row, resolved before any row is read."""

    schema: Schema
    key_indexes: tuple[int, ...]
    partition_indexes: tuple[int, ...]
    null_literal: str
    on_type_error: str


def build_records(sources: Sequence[Source], plan: RecordPlan) -> Iterator[Record]:
    """Read every input in order, casting each row into the resolved schema.

    Columns a row does not carry come through as nulls, and columns the schema
    does not name are dropped. The sequence number counts rows across all
    inputs, so it preserves input appearance order for rows whose keys tie -
    including across sorted runs.
    """
    columns = plan.schema.columns
    sequence = 0
    for source in sources:
        for row in source.rows():
            location = f"{source.path}:{row.ordinal}"
            values = [
                _resolve_cell(row.values.get(column.name), column, plan.on_type_error, location)
                for column in columns
            ]
            yield Record(
                partition=partition_path(columns, values, plan.partition_indexes),
                key=tuple(comparable(values[index]) for index in plan.key_indexes),
                sequence=sequence,
                cells=tuple(format_value(value, plan.null_literal) for value in values),
            )
            sequence += 1


def _resolve_cell(value: Any, column: Column, on_type_error: str, location: str) -> Any:
    """Cast one cell, applying the configured policy when it will not parse."""
    if value is None:
        return None
    parsed, result = cast_value(value, column.type)
    if parsed:
        return result
    if on_type_error == FAIL:
        raise MergeError(f"{location}: cannot cast {value!r} to {column.type} for column {column.name!r}")
    return value if on_type_error == KEEP_STRING else None

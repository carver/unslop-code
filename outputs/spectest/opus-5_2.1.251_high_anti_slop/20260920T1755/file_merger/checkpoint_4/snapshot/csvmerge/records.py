"""Turning raw input rows into sortable, output-ready records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, NamedTuple, Sequence

from csvmerge.nested import CastContext, cast_field, parse_json_cell, to_json_text
from csvmerge.paths import FieldPath
from csvmerge.partition import partition_path
from csvmerge.schema import Column, Schema
from csvmerge.sources import Source
from csvmerge.types import DataType, Primitive
from csvmerge.values import comparable, format_value


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
    keys: tuple[FieldPath, ...]
    partitions: tuple[FieldPath, ...]
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
            context = CastContext(plan.on_type_error, f"{source.path}:{row.ordinal}")
            values = [
                _resolve_cell(row.values.get(column.name), column, context, source.typed)
                for column in columns
            ]
            yield Record(
                partition=partition_path(plan.partitions, values),
                key=tuple(comparable(path.read(values)) for path in plan.keys),
                sequence=sequence,
                cells=tuple(
                    _render(value, column.type, plan.null_literal)
                    for value, column in zip(values, columns)
                ),
            )
            sequence += 1


def _render(value: Any, declared: DataType, null_literal: str) -> str:
    """Spell one cast value as its CSV cell: canonical JSON for a nested column."""
    if isinstance(declared, Primitive) or value is None:
        return format_value(value, null_literal)
    return to_json_text(value)


def _resolve_cell(value: Any, column: Column, context: CastContext, typed: bool) -> Any:
    """Cast one cell, applying the configured policy when it will not parse.

    A nested column in a text format holds one JSON literal, which is read
    before the cast; a typed format hands the structure over as it is, so a
    string there stays a string.
    """
    if value is None:
        return None
    if typed or isinstance(column.type, Primitive):
        return cast_field(value, column.type, column.name, context)
    return parse_json_cell(value, column.type, column.name, context)

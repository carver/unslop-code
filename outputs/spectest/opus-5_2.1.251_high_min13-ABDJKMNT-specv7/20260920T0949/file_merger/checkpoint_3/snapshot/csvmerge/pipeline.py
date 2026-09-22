"""Turning input records into rendered, sortable output rows."""

from __future__ import annotations

from .casting import CastError, cast, render, sort_part
from .errors import ToolError
from .hive import segment_of
from .reader import CsvFormat
from .records import Record
from .schema import Schema
from .sources import open_records


class RowAligner:
    """Places each record's own fields at their position in the output schema.

    Records from JSON Lines name their fields line by line, so the mapping is
    cached per distinct field-name tuple rather than computed per record.
    """

    def __init__(self, schema: Schema):
        self._positions = {column.name: index for index, column in enumerate(schema.columns)}
        self._width = len(schema.columns)
        self._layouts: dict[tuple[str, ...], list[int | None]] = {}

    def align(self, record: Record) -> list[str | None]:
        layout = self._layouts.get(record.names)
        if layout is None:
            layout = [self._positions.get(name) for name in record.names]
            self._layouts[record.names] = layout

        row: list[str | None] = [None] * self._width
        for index, value in zip(layout, record.values):
            if index is not None:
                row[index] = value
        return row


class RowBuilder:
    """Casts one record into its output cells and its sort key.

    The sort key leads with the partition columns' directory segments, so the
    sorted stream arrives grouped by partition directory and the writer only
    ever holds one part file open (AMBIGUITIES T45). The remaining parts are
    the ``--key`` columns.
    """

    def __init__(self, schema: Schema, key_indexes, partition_indexes, on_type_error: str, null_literal: str):
        self._schema = schema
        self._aligner = RowAligner(schema)
        self._key_indexes = key_indexes
        self._partition_indexes = partition_indexes
        self._on_type_error = on_type_error
        self._null_literal = null_literal

    def build(self, record: Record) -> tuple[list, list[str]]:
        columns = self._schema.columns
        values = [
            None if text is None else cast(text, column.spec, self._on_type_error)
            for column, text in zip(columns, self._aligner.align(record))
        ]
        cells = [render(value, column.spec, self._null_literal) for column, value in zip(columns, values)]
        parts = [segment_of(values[index], columns[index].spec) for index in self._partition_indexes]
        parts += [sort_part(values[index], columns[index].spec) for index in self._key_indexes]
        return parts, cells


def prepared_rows(specs, fmt: CsvFormat, builder: RowBuilder):
    """Yield ``(key_parts, cells)`` for every input record, in input order.

    Records are produced file by file in command-line order, which is the input
    appearance order the stable sort later preserves for equal keys.
    """
    for spec in specs:
        with open_records(spec, fmt) as stream:
            for record in stream.records:
                try:
                    yield builder.build(record)
                except CastError as exc:
                    raise ToolError(f"{spec.path}:{record.position}: {exc}") from None

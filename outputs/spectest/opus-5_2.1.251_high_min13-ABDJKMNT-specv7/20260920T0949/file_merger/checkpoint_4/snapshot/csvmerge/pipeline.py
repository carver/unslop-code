"""Turning input records into rendered, sortable output rows."""

from __future__ import annotations

from .casting import CastError, sort_part
from .cells import JsonCellError, cast_cell, render_cell
from .errors import CastFailure, SourceFormatError
from .hive import segment_of
from .paths import value_at
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

    def align(self, record: Record) -> list:
        layout = self._layouts.get(record.names)
        if layout is None:
            layout = [self._positions.get(name) for name in record.names]
            self._layouts[record.names] = layout

        row: list = [None] * self._width
        for index, value in zip(layout, record.values):
            if index is not None:
                row[index] = value
        return row


class RowBuilder:
    """Casts one record into its output cells and its sort key.

    The sort key leads with the partition fields' directory segments, so the
    sorted stream arrives grouped by partition directory and the writer only
    ever holds one part file open (AMBIGUITIES T45). The remaining parts are
    the ``--key`` fields, each read out of its column by following its path.
    """

    def __init__(self, schema: Schema, key_fields, partition_fields, on_type_error: str, null_literal: str):
        self._schema = schema
        self._aligner = RowAligner(schema)
        self._key_fields = key_fields
        self._partition_fields = partition_fields
        self._on_type_error = on_type_error
        self._null_literal = null_literal

    def build(self, record: Record) -> tuple[list, list[str]]:
        columns = self._schema.columns
        values = [
            None if cell is None else cast_cell(cell, column.type, self._on_type_error, column.name)
            for column, cell in zip(columns, self._aligner.align(record))
        ]
        cells = [render_cell(value, column.type, self._null_literal) for column, value in zip(columns, values)]
        parts = [segment_of(self._leaf(values, field), field.spec) for field in self._partition_fields]
        parts += [sort_part(self._leaf(values, field), field.spec) for field in self._key_fields]
        return parts, cells

    def _leaf(self, values, field):
        """The primitive value one resolved path points at, or ``None``."""
        return value_at(values[field.column], field.steps)


def prepared_rows(specs, fmt: CsvFormat, builder: RowBuilder, nested_ok: bool):
    """Yield ``(key_parts, cells)`` for every input record, in input order.

    Records are produced file by file in command-line order, which is the input
    appearance order the stable sort later preserves for equal keys.
    """
    for spec in specs:
        with open_records(spec, fmt, nested_ok) as stream:
            for record in stream.records:
                try:
                    yield builder.build(record)
                except CastError as exc:
                    raise CastFailure(f"ERR 4 {exc} (file={spec.path} line={record.position})") from None
                except JsonCellError as exc:
                    raise SourceFormatError(f"ERR 5 {exc} (file={spec.path} line={record.position})") from None

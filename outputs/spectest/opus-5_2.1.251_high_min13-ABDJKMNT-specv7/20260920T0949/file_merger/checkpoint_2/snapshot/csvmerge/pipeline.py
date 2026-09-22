"""Turning input records into rendered, sortable output rows."""

from __future__ import annotations

from .casting import CastError, cast, render, sort_part
from .errors import ToolError
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


def prepared_rows(specs, schema: Schema, fmt: CsvFormat, key_indexes, on_type_error: str):
    """Yield ``(key_parts, cells)`` for every input record, in input order.

    Records are produced file by file in command-line order, which is the input
    appearance order the stable sort later preserves for equal keys.
    """
    aligner = RowAligner(schema)
    for spec in specs:
        with open_records(spec, fmt) as stream:
            for record in stream.records:
                try:
                    yield _prepare_row(aligner.align(record), schema, fmt, key_indexes, on_type_error)
                except CastError as exc:
                    raise ToolError(f"{spec.path}:{record.position}: {exc}") from None


def _prepare_row(texts, schema: Schema, fmt: CsvFormat, key_indexes, on_type_error: str):
    """Cast one row's cells, render them, and project the sort key."""
    values = [
        None if text is None else cast(text, column.spec, on_type_error)
        for column, text in zip(schema.columns, texts)
    ]
    cells = [render(value, column.spec, fmt.null_literal) for column, value in zip(schema.columns, values)]
    parts = [sort_part(values[index], schema.columns[index].spec) for index in key_indexes]
    return parts, cells

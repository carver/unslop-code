"""Turning input files into rendered, sortable output rows."""

from __future__ import annotations

from .casting import CastError, cast, render, sort_part
from .errors import ToolError
from .reader import CsvFormat, column_indexes, open_table, select
from .schema import Schema


def prepared_rows(paths, schema: Schema, fmt: CsvFormat, key_indexes, on_type_error: str):
    """Yield ``(key_parts, cells)`` for every input row, in input order.

    Rows are produced file by file in command-line order, which is the input
    appearance order the stable sort later preserves for equal keys.
    """
    for path in paths:
        with open_table(path, fmt) as (header, rows):
            indexes = column_indexes(header, schema)
            for row in rows:
                if not row:  # a blank line between records carries no data
                    continue
                try:
                    yield _prepare_row(select(row, indexes), schema, fmt, key_indexes, on_type_error)
                except CastError as exc:
                    raise ToolError(f"{path}: line {rows.line_num}: {exc}") from None


def _prepare_row(texts, schema: Schema, fmt: CsvFormat, key_indexes, on_type_error: str):
    """Cast one row's cells, render them, and project the sort key."""
    values = [
        None if fmt.is_null(text) else cast(text, column.spec, on_type_error)
        for column, text in zip(schema.columns, texts)
    ]
    cells = [render(value, column.spec, fmt.null_literal) for column, value in zip(schema.columns, values)]
    parts = [sort_part(values[index], schema.columns[index].spec) for index in key_indexes]
    return parts, cells

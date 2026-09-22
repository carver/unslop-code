"""Turning input records into output cells and comparable sort keys."""

from __future__ import annotations

from typing import Any

from column_types import FieldValue, Record, canonical_text
from csv_io import CsvOptions
from errors import TypeCastError
from schema import Column

# Key cells are compared rank first, so values of different kinds never meet:
# a null compares below every value of its column and text kept by
# --on-type-error=keep-string compares above them.
NULL_RANK = 0
VALUE_RANK = 1
TEXT_RANK = 2

KeyCell = list[Any]
ShapedRow = tuple[list[KeyCell], list[str]]


class RowKey:
    """Ordering of a shaped row.

    Ranked key cells compare as plain lists, so nulls come first ascending and
    last descending.  Rows with equal keys keep their order of appearance,
    which makes the sort stable in both directions.  The cells are lists rather
    than tuples so a row read back from a spill file compares exactly like one
    still held in memory.
    """

    __slots__ = ("cells", "seq", "descending")

    def __init__(self, cells: list[KeyCell], seq: int, descending: bool) -> None:
        self.cells = cells
        self.seq = seq
        self.descending = descending

    def __lt__(self, other: "RowKey") -> bool:
        if self.cells == other.cells:
            return self.seq < other.seq
        return other.cells < self.cells if self.descending else self.cells < other.cells


class RowShaper:
    """Casts records into the resolved schema and extracts their sort keys.

    Values arrive as raw text from CSV and TSV and already typed from JSON Lines
    and Parquet; both go through the column's parser, so the same cast rules and
    the same ``--on-type-error`` handling apply to every format.
    """

    def __init__(
        self,
        columns: list[Column],
        key_names: list[str],
        on_type_error: str,
        options: CsvOptions,
    ) -> None:
        positions = {column.name: index for index, column in enumerate(columns)}
        self._columns = columns
        self._key_indexes = [positions[name] for name in key_names]
        self._on_type_error = on_type_error
        self._options = options

    def shape(self, record: Record) -> ShapedRow:
        """Return the row's key cells and the text of its output cells."""
        key_cells, output_cells = [], []
        for column in self._columns:
            key_cell, output = self._cast(column, record.get(column.name))
            key_cells.append(key_cell)
            output_cells.append(output)
        return [key_cells[index] for index in self._key_indexes], output_cells

    def _cast(self, column: Column, value: FieldValue) -> tuple[KeyCell, str]:
        if value is None:
            return self._null()
        text = canonical_text(value)
        try:
            parsed = column.type.parse(text)
        except ValueError as error:
            return self._on_failure(column, text, error)
        return [VALUE_RANK, column.type.sort_value(parsed)], column.type.render(parsed)

    def _on_failure(self, column: Column, text: str, error: ValueError) -> tuple[KeyCell, str]:
        if self._on_type_error == "fail":
            raise TypeCastError(f"column {column.name!r}: {error}")
        if self._on_type_error == "keep-string":
            return [TEXT_RANK, text], text
        return self._null()

    def _null(self) -> tuple[KeyCell, str]:
        return [NULL_RANK], self._options.null_literal

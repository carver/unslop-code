"""Turning input records into output cells and comparable sort keys."""

from __future__ import annotations

from typing import Any

from casting import CastContext, KeptText, rendered
from csv_io import CsvOptions
from field_paths import FieldPath
from partitions import segment
from records import SourceRecord
from schema import Column

# Key cells are compared rank first, so values of different kinds never meet:
# a null compares below every value of its column and text kept by
# --on-type-error=keep-string compares above them.
NULL_RANK = 0
VALUE_RANK = 1
TEXT_RANK = 2

KeyCell = list[Any]

# A row ready to be sorted: the directory segments of its partition, the cells
# of its sort key and the text of its output cells.
ShapedRow = tuple[list[str], list[KeyCell], list[str]]


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
    and Parquet; both go through the column's type, so the same cast rules and
    the same ``--on-type-error`` handling apply to every format.  Sort keys and
    partition values are then read out of the cast row by field path, which is
    how a leaf inside a struct, an array or a map can be sorted on.
    """

    def __init__(
        self,
        columns: list[Column],
        key_paths: list[FieldPath],
        partition_paths: list[FieldPath],
        on_type_error: str,
        options: CsvOptions,
    ) -> None:
        self._columns = columns
        self._key_paths = key_paths
        self._partition_paths = partition_paths
        self._on_type_error = on_type_error
        self._options = options

    def shape(self, record: SourceRecord) -> ShapedRow:
        """Return the row's partition, its key cells and its output cells."""
        context = CastContext(self._on_type_error, record.origin)
        values = {
            column.name: column.type.cast(
                record.values.get(column.name), context.child(column.name)
            )
            for column in self._columns
        }
        return (
            [self._segment(path, values) for path in self._partition_paths],
            [self._key_cell(path, values) for path in self._key_paths],
            [self._cell(column, values[column.name]) for column in self._columns],
        )

    def _cell(self, column: Column, value: object) -> str:
        """The output text of one column: its null literal, or the cast value."""
        if value is None:
            return self._options.null_literal
        return rendered(column.type, value)

    def _key_cell(self, path: FieldPath, values: dict[str, object]) -> KeyCell:
        """The ranked sort value the path names, null where the row has none."""
        value = path.read(values)
        if value is None:
            return [NULL_RANK]
        if isinstance(value, KeptText):
            return [TEXT_RANK, str(value)]
        return [VALUE_RANK, path.type.sort_value(value)]

    def _segment(self, path: FieldPath, values: dict[str, object]) -> str:
        """The directory name of one partition path, from its cast value."""
        value = path.read(values)
        return segment(path.text, None if value is None else rendered(path.type, value))

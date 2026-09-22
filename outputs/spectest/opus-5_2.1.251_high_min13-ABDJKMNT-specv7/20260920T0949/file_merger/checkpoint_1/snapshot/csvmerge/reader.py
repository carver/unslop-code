"""Reading input CSVs: dialect configuration, header handling and alignment."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class CsvFormat:
    """The input dialect plus the literal that stands for a null value."""

    quotechar: str = '"'
    escapechar: str | None = "\\"
    null_literal: str = ""

    def is_null(self, text: str | None) -> bool:
        """A cell is null when it is absent, empty, or equal to the null literal."""
        return text is None or text == "" or text == self.null_literal


@contextmanager
def open_table(path: str, fmt: CsvFormat):
    """Yield ``(header, rows)`` for one input file; an empty file yields no rows."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(
            handle,
            delimiter=",",
            quotechar=fmt.quotechar,
            escapechar=fmt.escapechar,
            doublequote=True,
        )
        header = next(reader, None)
        yield (header or []), (reader if header else iter(()))


def column_indexes(header, schema) -> list[int | None]:
    """Position of each schema column inside ``header``, or None when absent."""
    positions = {name: index for index, name in enumerate(header)}
    return [positions.get(column.name) for column in schema.columns]


def select(row, indexes) -> list[str | None]:
    """Pick the schema's cells out of one input row, padding what is missing."""
    return [None if index is None or index >= len(row) else row[index] for index in indexes]

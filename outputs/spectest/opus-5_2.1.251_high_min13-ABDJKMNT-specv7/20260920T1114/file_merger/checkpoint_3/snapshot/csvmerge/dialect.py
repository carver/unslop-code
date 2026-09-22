"""The CSV dialect shared by the delimited reader and the output writer."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class CsvDialect:
    """How CSV cells are quoted, escaped and spelled when null.

    Checkpoint 2 applies these settings to the output as well as to CSV inputs;
    quotes are always escaped by doubling (ambiguity T36).
    """

    quotechar: str = '"'
    escapechar: str = "\\"
    null_literal: str = ""

    def is_null(self, text: str) -> bool:
        """Empty cells are missing values, as is the configured null literal."""
        return text == "" or text == self.null_literal

    def format_row(self, cells: list[str]) -> str:
        """Render one output line, quoting only the cells that need it."""
        buffer = io.StringIO(newline="")
        csv.writer(
            buffer,
            delimiter=",",
            quotechar=self.quotechar,
            escapechar=self.escapechar,
            doublequote=True,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        ).writerow(cells)
        return buffer.getvalue()

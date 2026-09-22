"""Reading input CSVs and writing the merged CSV.

Inputs are UTF-8, comma delimited and carry a header row.  The quote and
escape characters are configurable; the output dialect is fixed so that runs
are reproducible.
"""

from __future__ import annotations

import csv
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TextIO

# The output is always RFC-4180 with doubled quotes and "\n" line endings.
OUTPUT_DIALECT = {
    "delimiter": ",",
    "quotechar": '"',
    "doublequote": True,
    "escapechar": None,
    "lineterminator": "\n",
    "quoting": csv.QUOTE_MINIMAL,
}

Record = dict[str, str]


@dataclass(frozen=True)
class CsvOptions:
    """Dialect details that the caller may override on the command line."""

    quotechar: str = '"'
    escapechar: str = "\\"
    null_literal: str = ""

    def is_null(self, text: str) -> bool:
        """An empty cell, or one holding the null literal, carries no value."""
        return text == "" or text == self.null_literal


@contextmanager
def open_csv(path: Path, options: CsvOptions) -> Iterator[tuple[list[str], Iterator[Record]]]:
    """Open ``path`` and yield its header together with a record iterator.

    Cells missing from a short row are filled with the null literal; cells
    beyond the header are collected under the ``None`` key and ignored.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(
            handle,
            delimiter=",",
            quotechar=options.quotechar,
            escapechar=options.escapechar,
            doublequote=True,
            restval=options.null_literal,
        )
        yield reader.fieldnames or [], reader


@contextmanager
def open_output(destination: str) -> Iterator[TextIO]:
    """Yield a text stream for ``destination``; ``-`` means standard output."""
    if destination == "-":
        stream = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="", closefd=False)
    else:
        stream = open(destination, "w", encoding="utf-8", newline="")
    with stream:
        yield stream

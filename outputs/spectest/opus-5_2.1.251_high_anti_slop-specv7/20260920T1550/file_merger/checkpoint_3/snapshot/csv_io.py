"""Reading delimited inputs and writing the merged CSV.

CSV inputs are UTF-8, comma delimited and carry a header row; the quote and
escape characters are configurable and are used for the output too.  TSV inputs
are tab delimited with no quoting at all, so a literal tab inside a field widens
the row and is reported instead of silently shifting cells.

The output is always comma delimited with ``"\n"`` line endings and doubled
quotes, and a file destination is replaced atomically once the last row has
been written.  :mod:`output` writes the partitioned outputs with the
same dialect.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence, TextIO

from column_types import Record
from errors import DataError
from inference import Candidates, observe
from streams import open_text


@dataclass(frozen=True)
class CsvOptions:
    """Dialect details that the caller may override on the command line."""

    quotechar: str = '"'
    escapechar: str = "\\"
    null_literal: str = ""

    def is_null(self, text: str) -> bool:
        """An empty cell, or one holding the null literal, carries no value."""
        return text == "" or text == self.null_literal


class CsvReader:
    """A comma separated input: a header row, then rows of raw text cells.

    Cells missing from a short row and cells holding the null literal read as
    missing; cells beyond the header are ignored.
    """

    format = "csv"
    # Set by formats where a wider row means a delimiter leaked into a field.
    extra_cells_error: str | None = None

    def __init__(self, path: Path, compression: str, options: CsvOptions) -> None:
        self._path = path
        self._compression = compression
        self._options = options

    def records(self) -> Iterator[Record]:
        """Stream the rows of the input, keyed by column name."""
        with self._reader() as reader:
            yield from self._rows(reader)

    def scan(self) -> Candidates:
        """Type every column from its cells, keeping header-only columns too."""
        with self._reader() as reader:
            candidates: Candidates = {name: set() for name in reader.fieldnames or []}
            return observe(self._rows(reader), candidates)

    def _dialect(self) -> dict[str, object]:
        return {
            "delimiter": ",",
            "quotechar": self._options.quotechar,
            "escapechar": self._options.escapechar,
            "doublequote": True,
        }

    @contextmanager
    def _reader(self) -> Iterator[csv.DictReader]:
        with open_text(self._path, self._compression) as handle:
            yield csv.DictReader(handle, restval="", **self._dialect())

    def _rows(self, reader: csv.DictReader) -> Iterator[Record]:
        for row in reader:
            if row.pop(None, None) is not None and self.extra_cells_error:
                raise DataError(
                    f"{self._path}: line {reader.line_num}: more cells than the header has "
                    f"columns; {self.extra_cells_error}"
                )
            yield {
                name: None if self._options.is_null(text) else text for name, text in row.items()
            }


class TsvReader(CsvReader):
    """A tab separated input: like CSV, but unquoted and with no escapes."""

    format = "tsv"
    extra_cells_error = "a TSV field may not contain a tab"

    def _dialect(self) -> dict[str, object]:
        return {"delimiter": "\t", "quoting": csv.QUOTE_NONE}


def output_dialect(options: CsvOptions) -> dict[str, object]:
    """The dialect the merged CSV is written with.

    Comma delimited with ``"\n"`` line endings, quoting only where a cell needs
    it, using the configured quote and escape characters.  Quotes are doubled,
    so the escape character only ever matters on the way in.
    """
    return {
        "delimiter": ",",
        "quotechar": options.quotechar,
        "doublequote": True,
        "escapechar": options.escapechar,
        "lineterminator": "\n",
        "quoting": csv.QUOTE_MINIMAL,
    }


class RowFormatter:
    """Renders rows in the output dialect, one at a time.

    Part files are cut by their size on disk, which means the text of a row has
    to be known before it is written, so the sharded writers render rows
    through this instead of handing them to a :class:`csv.writer` directly.
    """

    def __init__(self, options: CsvOptions) -> None:
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer, **output_dialect(options))

    def render(self, cells: Sequence[str]) -> str:
        """The exact text this row is written as, line ending included."""
        self._buffer.seek(0)
        self._buffer.truncate()
        self._writer.writerow(cells)
        return self._buffer.getvalue()


@contextmanager
def open_output(destination: str) -> Iterator[TextIO]:
    """Yield a text stream for ``destination``; ``-`` means standard output.

    A path is written to a temporary file next to it and renamed into place, so
    a failed run never leaves a partial output behind.
    """
    if destination == "-":
        with open(sys.stdout.fileno(), "w", encoding="utf-8", newline="", closefd=False) as stream:
            yield stream
        return

    final = Path(destination)
    partial = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=final.parent,
        prefix=f"{final.name}.",
        suffix=".part",
        delete=False,
    )
    try:
        with partial as stream:
            yield stream
        os.replace(partial.name, final)
    finally:
        Path(partial.name).unlink(missing_ok=True)

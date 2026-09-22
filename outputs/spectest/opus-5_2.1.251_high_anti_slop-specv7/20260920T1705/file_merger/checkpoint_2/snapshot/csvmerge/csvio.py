"""Delimited input (CSV and TSV) and the fixed CSV output dialect.

CSV inputs follow RFC-4180 with tunable quoting; TSV inputs are tab separated
and unquoted, so a literal tab inside a field is indistinguishable from a
separator and is reported instead of silently splitting the row.  The output
dialect is fixed by the spec: comma delimited, ``"`` quoted, quotes escaped by
doubling and ``\\n`` line endings.
"""

from __future__ import annotations

import csv
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterator, Sequence

from .errors import SourceFormatError
from .formats import FileFormat, InputRow, Source, open_text

_OUTPUT_DIALECT = {
    "delimiter": ",",
    "quotechar": '"',
    "doublequote": True,
    "escapechar": None,
    "lineterminator": "\n",
    "quoting": csv.QUOTE_MINIMAL,
}

_TSV_OPTIONS = {
    "delimiter": "\t",
    "quoting": csv.QUOTE_NONE,
    "quotechar": None,
    "escapechar": None,
}


def _reader_options(source: Source) -> dict[str, Any]:
    """Keyword arguments for :func:`csv.reader` matching the source format."""
    if source.format is FileFormat.TSV:
        return dict(_TSV_OPTIONS)
    return {
        "delimiter": ",",
        "quotechar": source.dialect.quotechar,
        "doublequote": True,
        "escapechar": source.dialect.escapechar,
    }


def read_header(source: Source) -> tuple[str, ...]:
    """Return the column names of a file, or nothing if it has none."""
    with open_text(source.path, source.compression) as handle:
        return tuple(next(csv.reader(handle, **_reader_options(source)), ()))


def read_rows(source: Source) -> Iterator[InputRow]:
    """Yield each data row as a mapping of column name to text.

    Empty cells and cells holding the null literal map to ``None``; columns
    absent from the file's header are simply missing from the mapping, which
    lets schema inference tell "not provided here" apart from "empty here".
    """
    with open_text(source.path, source.compression) as handle:
        reader = csv.reader(handle, **_reader_options(source))
        header = next(reader, None)
        if header is None:
            return
        nulls = source.dialect.null_texts
        for row in reader:
            if source.format is FileFormat.TSV and len(row) > len(header):
                raise SourceFormatError(
                    f"{source.path}:{reader.line_num}: row has {len(row)} fields but the "
                    f"header has {len(header)}; TSV fields may not contain literal tabs"
                )
            yield InputRow(
                reader.line_num,
                {name: None if text in nulls else text for name, text in zip(header, row)},
            )


@contextmanager
def open_output(destination: str) -> Iterator[IO[str]]:
    """Open the output destination, or hand out stdout for ``-``.

    A regular file is written to a hidden sibling and renamed into place once
    the last row is out, so a run that fails midway leaves no half-written CSV
    behind.  Destinations that cannot be renamed into place — ``/dev/null``, a
    fifo, a process substitution — are written through directly.
    """
    if destination == "-":
        yield sys.stdout
        return
    target = Path(destination)
    if target.exists() and not target.is_file():
        with open(target, "w", newline="", encoding="utf-8") as handle:
            yield handle
        return
    scratch = target.with_name(f".{target.name}.partial")
    try:
        with open(scratch, "w", newline="", encoding="utf-8") as handle:
            yield handle
        os.replace(scratch, target)
    finally:
        scratch.unlink(missing_ok=True)


def write_rows(
    handle: IO[str],
    header: Sequence[str],
    rows: Iterator[Sequence[str | None]],
    null_literal: str,
) -> None:
    """Write the header and every row, spelling ``None`` as the null literal."""
    writer = csv.writer(handle, **_OUTPUT_DIALECT)
    writer.writerow(header)
    for row in rows:
        writer.writerow([null_literal if cell is None else cell for cell in row])

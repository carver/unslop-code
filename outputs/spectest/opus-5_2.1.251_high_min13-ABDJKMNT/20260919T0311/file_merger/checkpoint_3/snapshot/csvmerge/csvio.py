"""The CSV dialects: how inputs are parsed and how the output is written."""
from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from contextlib import contextmanager
from typing import Iterable, Sequence

#: The output dialect is deterministic and independent of the input flags.
_WRITER_DIALECT = {
    "delimiter": ",",
    "quotechar": '"',
    "doublequote": True,
    "escapechar": None,
    "lineterminator": "\n",
    "quoting": csv.QUOTE_MINIMAL,
}


def reader_dialect(quotechar: str, escapechar: str | None) -> dict:
    """csv.reader keyword arguments for the input files."""
    return {
        "delimiter": ",",
        "quotechar": quotechar,
        "escapechar": escapechar,
        "doublequote": True,
    }


@contextmanager
def open_output(path: str):
    """Open the output sink; `-` means stdout, a path is written atomically.

    A file destination is built beside itself under a temporary name and moved
    into place only once it is complete, so an interrupted run never leaves a
    half-written file where the merged output should be.
    """
    if path == "-":
        sys.stdout.reconfigure(newline="")
        yield sys.stdout
        return

    handle = tempfile.NamedTemporaryFile(
        "w", dir=os.path.dirname(os.path.abspath(path)), prefix=".merge-files-",
        suffix=".tmp", delete=False, newline="", encoding="utf-8",
    )
    try:
        with handle:
            yield handle
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.remove(handle.name)


def render_row(values: Sequence[str]) -> str:
    """One row in the canonical output dialect, line terminator included."""
    buffer = io.StringIO()
    csv.writer(buffer, **_WRITER_DIALECT).writerow(values)
    return buffer.getvalue()


def write_rows(stream, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write the header and every row in the canonical output dialect."""
    writer = csv.writer(stream, **_WRITER_DIALECT)
    writer.writerow(header)
    writer.writerows(rows)

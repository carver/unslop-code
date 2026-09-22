"""Writing the merged result: one CSV, in the configured dialect, written atomically."""

from __future__ import annotations

import csv
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable, Iterator, TextIO

from csvmerge.dialect import CsvDialect
from csvmerge.errors import EXIT_ERROR, MergeError

STDOUT = "-"


def write_output(
    destination: str, dialect: CsvDialect, header: list[str], rows: Iterable[list[str]]
) -> None:
    """Write the header and rows, quoting as the CSV dialect flags ask."""
    with _open_destination(destination) as handle:
        writer = csv.writer(
            handle,
            delimiter=",",
            quotechar=dialect.quotechar,
            escapechar=dialect.escapechar,
            doublequote=True,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerow(header)
        writer.writerows(rows)


@contextmanager
def _open_destination(destination: str) -> Iterator[TextIO]:
    """Yield the stream to write to; a file appears only once it is complete."""
    if destination == STDOUT:
        yield sys.stdout
        return
    target = Path(destination)
    try:
        scratch = NamedTemporaryFile(
            "w",
            dir=target.parent,
            prefix=f".{target.name}-",
            delete=False,
            newline="",
            encoding="utf-8",
        )
    except OSError as error:
        raise MergeError(
            f"cannot write output {destination}: {error}", EXIT_ERROR
        ) from error
    try:
        with scratch as handle:
            yield handle
        os.replace(scratch.name, target)
    except BaseException:
        os.unlink(scratch.name)
        raise

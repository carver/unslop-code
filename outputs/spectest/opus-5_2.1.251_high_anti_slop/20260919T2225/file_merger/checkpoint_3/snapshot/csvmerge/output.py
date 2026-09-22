"""Writing the merged CSV, to stdout or atomically to a file."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from tempfile import NamedTemporaryFile
from typing import IO

from .dialect import CsvDialect


@contextmanager
def open_output(path: str) -> Iterator[IO[str]]:
    """Open the output sink: ``-`` means stdout, anything else a UTF-8 file.

    A file is built beside its destination and renamed into place on success, so
    a failed run never leaves a half-written CSV behind.
    """
    if path == "-":
        yield sys.stdout
        return
    pending = NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=os.path.dirname(os.path.abspath(path)),
        prefix=".csvmerge-", delete=False,
    )
    try:
        with pending as stream:
            yield stream
        os.replace(pending.name, path)
    except BaseException:
        os.unlink(pending.name)
        raise


def write_csv(stream: IO[str], dialect: CsvDialect, header: Iterable[str], rows: Iterable[list[str]]) -> None:
    """Write the header followed by ``rows``, streaming them one at a time."""
    writer = dialect.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)

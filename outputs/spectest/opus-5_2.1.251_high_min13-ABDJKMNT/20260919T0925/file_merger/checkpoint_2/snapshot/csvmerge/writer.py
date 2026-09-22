"""Writing the merged output: to stdout, or atomically onto a file path."""

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import MergeError


@contextmanager
def open_output(destination):
    """Yield a text stream for `destination`, or stdout when it is ``-``.

    A file target is written through a temporary file in the same directory and then
    renamed over the destination, so concurrent readers see either the previous file
    or the complete new one, and a failed run leaves neither behind (AMBIGUITIES T29).
    """
    if destination == "-":
        yield sys.stdout
        return

    target = Path(destination)
    handle = _temporary_beside(target)
    try:
        with handle:
            yield handle
    except BaseException:
        os.unlink(handle.name)
        raise
    os.replace(handle.name, target)


def write_rows(stream, header, rows, dialect):
    """Write the header and rows using the configured CSV dialect."""
    writer = dialect.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)


def _temporary_beside(target):
    try:
        return tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".part",
            delete=False,
        )
    except OSError as error:
        raise MergeError(f"cannot write output {target}: {error}") from error

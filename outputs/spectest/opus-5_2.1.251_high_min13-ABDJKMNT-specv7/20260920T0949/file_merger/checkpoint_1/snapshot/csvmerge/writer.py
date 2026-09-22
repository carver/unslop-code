"""Writing the merged result in the deterministic output dialect."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_output(path: str):
    """Yield the destination handle; ``-`` means stdout.

    A file destination is written through a sibling temporary file and moved
    into place only once the whole result has been produced, so a run that
    fails part way through leaves neither a partial output nor a stray file.
    """
    if path == "-":
        yield sys.stdout
        return

    target = Path(path)
    scratch = tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False
    )
    try:
        with scratch as handle:
            yield handle
    except BaseException:
        os.unlink(scratch.name)
        raise
    os.replace(scratch.name, target)


def write_csv(handle, header, rows) -> None:
    """Write the header and rows with comma, doubled quotes and ``\\n`` endings."""
    writer = csv.writer(
        handle,
        delimiter=",",
        quotechar='"',
        doublequote=True,
        escapechar=None,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    writer.writerow(header)
    writer.writerows(rows)

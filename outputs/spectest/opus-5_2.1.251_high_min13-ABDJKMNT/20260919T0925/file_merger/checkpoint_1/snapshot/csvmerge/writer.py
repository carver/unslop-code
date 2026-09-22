"""Writing the merged output in the fixed output dialect."""

from __future__ import annotations

import csv
import sys
from contextlib import contextmanager

from .errors import MergeError


@contextmanager
def open_output(destination):
    """Open `destination` for writing, or yield stdout when it is ``-``."""
    if destination == "-":
        yield sys.stdout
        return
    try:
        with open(destination, "w", encoding="utf-8", newline="") as stream:
            yield stream
    except OSError as error:
        raise MergeError(f"cannot write output {destination}: {error}") from error


def write_rows(stream, header, rows):
    """Write the header and rows as comma-delimited, quote-doubling CSV."""
    writer = csv.writer(
        stream,
        delimiter=",",
        quotechar='"',
        doublequote=True,
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writerow(header)
    writer.writerows(rows)

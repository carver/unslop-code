"""Writing the merged result in the fixed output dialect."""

from __future__ import annotations

import csv
import sys
from contextlib import contextmanager
from typing import Iterable, Iterator

from csvmerge.errors import MergeError

STDOUT = "-"


def write_output(destination: str, header: list[str], rows: Iterable[list[str]]) -> None:
    """Write the header and rows as comma-separated, double-quote-escaped CSV."""
    with _open_destination(destination) as handle:
        writer = csv.writer(
            handle,
            delimiter=",",
            quotechar='"',
            doublequote=True,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writerow(header)
        writer.writerows(rows)


@contextmanager
def _open_destination(destination: str) -> Iterator:
    if destination == STDOUT:
        yield sys.stdout
        return
    try:
        handle = open(destination, "w", newline="", encoding="utf-8")
    except OSError as error:
        raise MergeError(f"cannot write output {destination}: {error}") from error
    with handle:
        yield handle

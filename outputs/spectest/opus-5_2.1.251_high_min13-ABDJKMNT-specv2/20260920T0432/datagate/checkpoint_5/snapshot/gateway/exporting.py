"""Rendering a page of a dataset as a downloadable CSV file."""

import csv
import io

from .tabular import Cell

# `\n` survives naive line splitting as well as a real parser; the spec leaves
# the choice open.
LINE_TERMINATOR = "\n"


def to_csv(columns: list[str], rows: list[list[Cell]]) -> str:
    """The header row followed by `rows`, quoted only where CSV needs it."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator=LINE_TERMINATOR)
    writer.writerow(columns)
    writer.writerows(rows)
    return out.getvalue()

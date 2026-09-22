"""Delimiter inference and CSV parsing into a rectangular table."""

import csv
import io
from dataclasses import dataclass

from datagate_core.errors import NonTabularError
from datagate_core.values import Value, infer_value

#: A row paired with its 1-based source-file row number (see T16).
NumberedRow = tuple[int, list[Value]]

#: Tried in this order, which also breaks ties between equally good candidates.
CANDIDATE_DELIMITERS = (",", ";", "\t")

#: Documents starting with one of these are markup or JSON, never a CSV table.
MARKUP_PREFIXES = ("<", "{", "[")


@dataclass(frozen=True)
class Table:
    """Column names plus rows of already type-inferred values, in source order."""

    columns: list[str]
    rows: list[list[Value]]


def parse_table(text: str) -> Table:
    """Parse delimited `text` into a `Table`, or raise `NonTabularError`."""
    if not text.strip():
        raise NonTabularError("the source is empty")
    if text.lstrip().startswith(MARKUP_PREFIXES):
        raise NonTabularError("the source is markup or JSON, not a delimited table")
    return build_table(_best_grid(text))


def build_table(grid: list[list[str]]) -> Table:
    """Read a grid of raw cells - header row first - as a rectangular `Table`."""
    if len(grid) < 2:
        raise NonTabularError("a table needs a header row and at least one data row")

    columns = grid[0]
    return Table(
        columns=columns,
        rows=[_align(row, len(columns)) for row in grid[1:]],
    )


def _best_grid(text: str) -> list[list[str]]:
    """Parse with each candidate delimiter and keep the most table-like result."""
    grids = [_read_grid(text, delimiter) for delimiter in CANDIDATE_DELIMITERS]
    scored = [(_score(grid), grid) for grid in grids if len(grid[0]) > 1]
    if not scored:
        raise NonTabularError(
            "no delimiter out of ',', ';' or tab produces more than one column"
        )
    return max(scored, key=lambda pair: pair[0])[1]


def _read_grid(text: str, delimiter: str) -> list[list[str]]:
    """Parse `text` with `delimiter`, dropping lines that hold no content."""
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        # Stray NULs and bare newlines inside fields: decoded binary, not a table.
        raise NonTabularError("the source is not text in a delimited format")
    return [row for row in rows if any(cell.strip() for cell in row)] or [[]]


def _score(grid: list[list[str]]) -> tuple[float, int]:
    """Rank a candidate parse by row-width consistency, then by column count."""
    width = len(grid[0])
    consistent = sum(1 for row in grid if len(row) == width)
    return consistent / len(grid), width


def _align(row: list[str], width: int) -> list[Value]:
    """Pad or trim a row to the header width and infer each cell's type."""
    padded = row[:width] + [""] * (width - len(row))
    return [infer_value(cell) for cell in padded]

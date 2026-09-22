"""Construction of the ``(columns, rows)`` table every source format is parsed into."""

from .errors import DataGateError
from .values import Value, coerce

Table = tuple[list[str], list[list[Value]]]


def build_table(grid: list[list[Value]]) -> Table:
    """Turn a grid of cells into column names plus typed rows, in source column order.

    Blank rows are dropped, the first remaining row names the columns, and every later
    row is truncated or padded to the header's width so that rows stay aligned with
    ``columns``. A grid without a header row or without a data row is not tabular and
    raises a 400 error.
    """
    rows = [row for row in grid if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise DataGateError(
            "source content is not tabular: expected a header row and at least one "
            "data row",
            400,
        )

    columns = [str(cell).strip() for cell in rows[0]]
    return columns, [_fit(row, len(columns)) for row in rows[1:]]


def _fit(row: list[Value], width: int) -> list[Value]:
    """Coerce a data row to JSON values and square it off to ``width`` columns."""
    cells = [coerce(cell) for cell in row[:width]]
    return cells + [""] * (width - len(cells))

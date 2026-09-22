"""The table every source format is parsed into: its filetype, columns and rows."""

from dataclasses import dataclass

from .errors import DataGateError
from .values import Value, coerce

CSV = "csv"
EXCEL = "excel"


@dataclass(frozen=True)
class Table:
    """A parsed source: the format it was read as, plus its columns and typed rows.

    ``filetype`` is one of ``CSV`` or ``EXCEL`` and is reported by the ingestion
    metadata that ``enrich=yes`` attaches to a dataset.
    """

    filetype: str
    columns: list[str]
    rows: list[list[Value]]


def build_table(grid: list[list[Value]], filetype: str) -> Table:
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
    return Table(
        filetype=filetype,
        columns=columns,
        rows=[_fit(row, len(columns)) for row in rows[1:]],
    )


def _fit(row: list[Value], width: int) -> list[Value]:
    """Coerce a data row to JSON values and square it off to ``width`` columns."""
    cells = [coerce(cell) for cell in row[:width]]
    return cells + [""] * (width - len(cells))

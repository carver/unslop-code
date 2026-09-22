"""Rendering a stored table into a dataset response body under its query controls."""

from datagate_core.controls import Controls, LISTS
from datagate_core.tables import Table

Value = str | int | float
#: A row paired with its 1-based source-file row number (see T16).
NumberedRow = tuple[int, list[Value]]


def render(table: Table, controls: Controls) -> dict:
    """Build the `columns`, `rows` and `total` of a `/datasets/<id>` response."""
    numbered = list(enumerate(table.rows, start=1))
    if controls.sort_column:
        index = table.columns.index(controls.sort_column)
        numbered = _sorted_by(numbered, index, controls.descending)

    page = numbered[controls.offset : controls.offset + controls.size]
    body = {"columns": table.columns, "rows": _shape_rows(page, table.columns, controls)}
    if controls.show_total:
        body["total"] = len(table.rows)
    return body


def _sorted_by(rows: list[NumberedRow], index: int, descending: bool) -> list[NumberedRow]:
    """Stable sort on one column, keeping source order among equal values."""
    return sorted(rows, key=lambda numbered: _sort_key(numbered[1][index]), reverse=descending)


def _sort_key(value: Value) -> tuple[int, float, str]:
    """Order numbers numerically and ahead of all text, as SQL engines do (T17)."""
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0, value)


def _shape_rows(page: list[NumberedRow], columns: list[str], controls: Controls) -> list:
    """Render the page as arrays, or as objects keyed by column name."""
    if controls.shape == LISTS:
        return [row for _, row in page]
    return [_as_object(rowid, row, columns, controls.show_rowid) for rowid, row in page]


def _as_object(rowid: int, row: list[Value], columns: list[str], show_rowid: bool) -> dict:
    """One row as an object: `rowid` first, then the columns in source order."""
    fields: dict[str, Value] = {"rowid": rowid} if show_rowid else {}
    fields.update(zip(columns, row))
    return fields

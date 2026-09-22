"""Turning a stored dataset plus its query into the response body.

Rows are filtered first, then sorted, then paged, then shaped, so
`_offset`/`_size` always address positions in the filtered and sorted table and
`total` stays the count of the rows that passed the filters.
"""

from typing import Any

from .controls import QueryControls
from .filtering import ColumnFilter, filter_rows
from .parsing import Dataset, Row

ROWID_KEY = "rowid"


def build_body(dataset: Dataset, controls: QueryControls, filters: list[ColumnFilter]) -> dict[str, Any]:
    """Build the `ok`/`columns`/`rows`/`total` payload for one dataset query.

    An enriched dataset also reports the metadata it was ingested with; a
    non-enriched one carries no such keys at all rather than empty ones.
    """
    matching = filter_rows(dataset.rows, filters)
    page = _paged(matching, dataset.columns, controls)
    body = {"ok": True, "columns": dataset.columns, "rows": _shaped(page, dataset.columns, controls)}
    if controls.show_total:
        body["total"] = len(matching)
    return body | (dataset.metadata or {})


def select_page(dataset: Dataset, controls: QueryControls, filters: list[ColumnFilter]) -> list[Row]:
    """The rows one query addresses, unshaped -- what the CSV export writes out."""
    return _paged(filter_rows(dataset.rows, filters), dataset.columns, controls)


def _paged(rows: list[Row], columns: list[str], controls: QueryControls) -> list[Row]:
    ordered = _sorted_rows(rows, columns, controls)
    return ordered[controls.offset : controls.offset + controls.size]


def _sorted_rows(rows: list[Row], columns: list[str], controls: QueryControls) -> list[Row]:
    if controls.sort_column is None:
        return rows
    index = columns.index(controls.sort_column)
    return sorted(rows, key=lambda row: _ordering_key(row.values[index]), reverse=controls.descending)


def _ordering_key(value: Any) -> tuple[int, str, float]:
    """Order numbers among themselves, then text, the way SQL engines do."""
    if isinstance(value, str):
        return (1, value, 0.0)
    return (0, "", value)


def _shaped(rows: list[Row], columns: list[str], controls: QueryControls) -> list[Any]:
    if controls.shape == "lists":
        return [row.values for row in rows]
    return [_as_object(row, columns, controls.show_rowid) for row in rows]


def _as_object(row: Row, columns: list[str], show_rowid: bool) -> dict[str, Any]:
    """Map a row onto the header names, optionally led by its source row number."""
    identity = {ROWID_KEY: row.rowid} if show_rowid else {}
    return identity | dict(zip(columns, row.values))

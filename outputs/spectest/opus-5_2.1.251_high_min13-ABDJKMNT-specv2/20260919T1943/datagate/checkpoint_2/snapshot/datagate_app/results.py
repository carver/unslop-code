"""Turning a stored dataset plus its controls into the response body.

Rows are sorted first, then paged, then shaped, so `_offset`/`_size` always
address positions in the sorted table and `total` stays the full row count.
"""

from typing import Any

from .controls import QueryControls
from .parsing import Dataset, Row

ROWID_KEY = "rowid"


def build_body(dataset: Dataset, controls: QueryControls) -> dict[str, Any]:
    """Build the `ok`/`columns`/`rows`/`total` payload for one dataset query."""
    page = _sorted_rows(dataset, controls)[controls.offset : controls.offset + controls.size]
    body = {"ok": True, "columns": dataset.columns, "rows": _shaped(page, dataset.columns, controls)}
    if controls.show_total:
        body["total"] = len(dataset.rows)
    return body


def _sorted_rows(dataset: Dataset, controls: QueryControls) -> list[Row]:
    if controls.sort_column is None:
        return dataset.rows
    index = dataset.columns.index(controls.sort_column)
    return sorted(dataset.rows, key=lambda row: _ordering_key(row.values[index]), reverse=controls.descending)


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

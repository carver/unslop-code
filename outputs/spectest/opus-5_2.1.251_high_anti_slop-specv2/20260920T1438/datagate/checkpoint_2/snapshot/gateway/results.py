"""Turning a stored dataset plus a :class:`Query` into a response body."""

from gateway.query import OBJECTS, Query
from gateway.store import Dataset
from gateway.values import Value

#: Source-file row number of the header; data rows are numbered after it.
HEADER_ROWID = 1

#: A data row paired with the source-file row number it came from.
NumberedRow = tuple[int, list[Value]]


def build_body(dataset: Dataset, query: Query) -> dict:
    """Sort, paginate and shape ``dataset`` as ``query`` asks for."""
    rows = number_rows(dataset.rows)
    rows = sort_rows(rows, dataset.columns, query)
    page = rows[query.offset : query.offset + query.size]

    body = {
        "ok": True,
        "columns": dataset.columns,
        "rows": shape_rows(page, dataset.columns, query),
    }
    if query.show_total:
        body["total"] = len(dataset.rows)
    return body


def number_rows(rows: list[list[Value]]) -> list[NumberedRow]:
    """Attach source-file row numbers, which survive sorting and pagination."""
    return list(enumerate(rows, start=HEADER_ROWID + 1))


def sort_rows(
    rows: list[NumberedRow], columns: list[str], query: Query
) -> list[NumberedRow]:
    """Order ``rows`` by the requested column, keeping equal rows in source order."""
    if query.sort is None:
        return rows
    index = columns.index(query.sort)
    return sorted(
        rows, key=lambda row: sort_key(row[1], index), reverse=query.descending
    )


def sort_key(row: list[Value], index: int) -> tuple[int, float, str]:
    """Rank one cell, placing every number before every piece of text.

    A column may mix numbers and text, and a row parsed from a ragged source
    may not reach ``index`` at all; both compare as one totally ordered tuple.
    """
    value = row[index] if index < len(row) else ""
    if isinstance(value, str):
        return 1, 0.0, value
    return 0, value, ""


def shape_rows(rows: list[NumberedRow], columns: list[str], query: Query) -> list:
    """Render rows as arrays, or as objects keyed by column name."""
    if query.shape != OBJECTS:
        return [values for _, values in rows]
    return [as_object(rowid, values, columns, query) for rowid, values in rows]


def as_object(rowid: int, row: list[Value], columns: list[str], query: Query) -> dict:
    """Build one row object, led by ``rowid`` unless it is hidden."""
    fields = {"rowid": rowid} if query.show_rowid else {}
    fields.update(zip(columns, row))
    return fields

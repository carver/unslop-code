"""Turning a stored dataset plus a :class:`Query` into a response body."""

from time import perf_counter

from gateway.errors import GateError
from gateway.filters import Filter
from gateway.query import OBJECTS, Query
from gateway.store import Dataset
from gateway.values import Value

#: Source-file row number of the header; data rows are numbered after it.
HEADER_ROWID = 1

#: How long the filtering scan of one request may run before it is abandoned.
QUERY_TIMEOUT_SECONDS = 5.0

#: A data row paired with the source-file row number it came from.
NumberedRow = tuple[int, list[Value]]


def select_rows(dataset: Dataset, query: Query) -> tuple[list[NumberedRow], int]:
    """Filter, sort and paginate ``dataset``, in that order.

    Returns the requested page along with how many rows the filters left, which
    is counted before pagination cuts into them.
    """
    rows = filter_rows(number_rows(dataset.rows), query.filters)
    rows = sort_rows(rows, dataset.columns, query)
    return rows[query.offset : query.offset + query.size], len(rows)


def build_body(dataset: Dataset, query: Query) -> dict:
    """Select the rows ``query`` asks for and shape them into a response body.

    An enriched dataset answers with the description of itself made when it was
    ingested; one ingested without enrichment carries none of those fields.
    """
    page, total = select_rows(dataset, query)
    body = {
        "ok": True,
        "columns": dataset.columns,
        "rows": shape_rows(page, dataset.columns, query),
    }
    if query.show_total:
        body["total"] = total
    if dataset.metadata is not None:
        body.update(dataset.metadata)
    return body


def filter_rows(rows: list[NumberedRow], filters: list[Filter]) -> list[NumberedRow]:
    """Keep the rows satisfying every filter, in source order.

    The scan is the one part of a request that grows with the table rather
    than with the page, so it carries the time budget: a table large enough to
    outlast :data:`QUERY_TIMEOUT_SECONDS` is reported as a failed request
    instead of holding the connection open.
    """
    if not filters:
        return rows

    deadline = perf_counter() + QUERY_TIMEOUT_SECONDS
    kept = []
    for row in rows:
        if perf_counter() > deadline:
            raise GateError("Query timed out while filtering rows", 400)
        if all(condition.matches(row[1]) for condition in filters):
            kept.append(row)
    return kept


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

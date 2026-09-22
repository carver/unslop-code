"""Column filters: `<column>__<comparator>=<value>` on `/datasets/<id>`.

A filter key names a column and one of four comparators; every filter a request
carries has to hold for a row to survive. Parsing is strict -- an unknown
column, an unknown comparator or a repeated key is `HTTP 400` -- while query
parameters that carry no comparator at all are left to the control layer.
"""

import time
from dataclasses import dataclass
from typing import Any, Callable

from werkzeug.datastructures import MultiDict

from .errors import DataGateError
from .parsing import Row

SEPARATOR = "__"
CONTROL_PREFIX = "_"
# Wall-clock budget for evaluating the filters of one request (T30).
QUERY_TIMEOUT_SECONDS = 5.0
TIMEOUT_CHECK_ROWS = 512


def _as_text(stored: Any) -> str:
    """Render a stored cell the way the string comparators see it (T28)."""
    return stored if isinstance(stored, str) else str(stored)


def _as_number(stored: Any) -> float | None:
    """Float-parse a stored cell, or `None` when it is not numeric (T29)."""
    try:
        return float(stored)
    except ValueError:
        return None


def _less(stored: Any, limit: float) -> bool:
    number = _as_number(stored)
    return number is not None and number < limit


def _greater(stored: Any, limit: float) -> bool:
    number = _as_number(stored)
    return number is not None and number > limit


COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "exact": lambda stored, value: _as_text(stored) == value,
    "contains": lambda stored, value: value in _as_text(stored),
    "less": _less,
    "greater": _greater,
}
NUMERIC_COMPARATORS = ("less", "greater")


@dataclass(frozen=True)
class ColumnFilter:
    """One condition, bound to the position of the column it tests."""

    index: int
    comparator: str
    value: str | float

    def matches(self, row: Row) -> bool:
        return COMPARATORS[self.comparator](row.values[self.index], self.value)


def parse_filters(args: MultiDict, columns: list[str]) -> list[ColumnFilter]:
    """Read the filter parameters of a request against the dataset's `columns`."""
    filters = []
    for key, values in args.lists():
        if key.startswith(CONTROL_PREFIX) or SEPARATOR not in key:
            continue
        if len(values) > 1:
            raise DataGateError(f"Filter '{key}' must not be repeated", 400)
        filters.append(_build_filter(key, values[0], columns))
    return filters


def _build_filter(key: str, value: str, columns: list[str]) -> ColumnFilter:
    """Turn one `<column>__<comparator>` key into a filter, or fail with a 400."""
    column, comparator = key.rsplit(SEPARATOR, 1)
    if comparator not in COMPARATORS:
        raise DataGateError(f"'{comparator}' is not a comparator: use one of {', '.join(COMPARATORS)}", 400)
    if column not in columns:
        raise DataGateError(f"'{column}' is not a column of this dataset", 400)
    return ColumnFilter(columns.index(column), comparator, _filter_value(comparator, value, key))


def _filter_value(comparator: str, value: str, key: str) -> str | float:
    """Numeric comparators compare floats, so their filter value must parse as one."""
    if comparator not in NUMERIC_COMPARATORS:
        return value
    try:
        return float(value)
    except ValueError:
        raise DataGateError(f"'{key}' compares numbers, so its value must be numeric, got {value!r}", 400) from None


def filter_rows(rows: list[Row], filters: list[ColumnFilter]) -> list[Row]:
    """Keep the rows matching every filter, abandoning the scan if it runs long."""
    if not filters:
        return rows
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    kept = []
    for position, row in enumerate(rows):
        if position % TIMEOUT_CHECK_ROWS == 0 and time.monotonic() >= deadline:
            raise DataGateError("Query timed out while filtering rows", 400)
        if all(condition.matches(row) for condition in filters):
            kept.append(row)
    return kept

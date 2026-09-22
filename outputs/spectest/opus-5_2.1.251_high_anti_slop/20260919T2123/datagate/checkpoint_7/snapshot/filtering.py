"""Column-level filters of the form ``<column>__<comparator>=<value>``."""

import time
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from errors import DatagateError
from store import Cell, NumberedRow, Row

SEPARATOR = "__"
CONTROL_PREFIX = "_"
QUERY_TIMEOUT_SECONDS = 5.0


def _as_number(value: Cell) -> float | None:
    """Read a cell or filter value as a float, or None when it does not parse as one."""
    try:
        return float(value)
    except ValueError:
        return None


def _exact(cell: Cell, wanted: str) -> bool:
    return str(cell) == wanted


def _contains(cell: Cell, wanted: str) -> bool:
    return wanted in str(cell)


def _less(cell: Cell, wanted: float) -> bool:
    number = _as_number(cell)
    return number is not None and number < wanted


def _greater(cell: Cell, wanted: float) -> bool:
    number = _as_number(cell)
    return number is not None and number > wanted


COMPARATORS = {"exact": _exact, "contains": _contains, "less": _less, "greater": _greater}
NUMERIC_COMPARATORS = ("less", "greater")


@dataclass(frozen=True)
class Filter:
    """One condition, resolved against the dataset: which column, how to compare, what to."""

    position: int
    comparator: str
    wanted: str | float

    def matches(self, row: Row) -> bool:
        return COMPARATORS[self.comparator](row[self.position], self.wanted)


def parse_filters(args: MultiDict, columns: list[str]) -> tuple[Filter, ...]:
    """Collect the filters from a query string, rejecting anything unusable with 400.

    Control parameters and parameters without a `__` comparator suffix are not filters and are
    left alone here.
    """
    filters = []
    for name, values in args.lists():
        if name.startswith(CONTROL_PREFIX) or SEPARATOR not in name:
            continue
        if len(values) > 1:
            raise DatagateError(400, f"Repeated filter parameter: {name!r}")
        filters.append(_build_filter(name, values[0], columns))
    return tuple(filters)


def filter_rows(rows: list[NumberedRow], filters: tuple[Filter, ...]) -> list[NumberedRow]:
    """Keep the rows that satisfy every filter, abandoning a scan that outruns its time budget."""
    if not filters:
        return rows
    deadline = time.perf_counter() + QUERY_TIMEOUT_SECONDS
    kept = []
    for numbered in rows:
        if time.perf_counter() > deadline:
            raise DatagateError(400, f"Query timed out after {QUERY_TIMEOUT_SECONDS}s")
        if all(condition.matches(numbered[1]) for condition in filters):
            kept.append(numbered)
    return kept


def _build_filter(name: str, value: str, columns: list[str]) -> Filter:
    """Resolve one `<column>__<comparator>` parameter name against the dataset's columns.

    The split is on the last `__` so that column names containing one stay addressable.
    """
    column, _, comparator = name.rpartition(SEPARATOR)
    if comparator not in COMPARATORS:
        raise DatagateError(
            400,
            f"Filter {name!r} must use one of the comparators "
            f"{', '.join(COMPARATORS)}, got {comparator!r}",
        )
    if column not in columns:
        raise DatagateError(400, f"Filter {name!r} must name a dataset column, got {column!r}")
    return Filter(columns.index(column), comparator, _wanted_value(name, comparator, value))


def _wanted_value(name: str, comparator: str, value: str) -> str | float:
    """Numeric comparators compare floats, so their filter value has to parse as one."""
    if comparator not in NUMERIC_COMPARATORS:
        return value
    number = _as_number(value)
    if number is None:
        raise DatagateError(400, f"Filter {name!r} needs a numeric value, got {value!r}")
    return number

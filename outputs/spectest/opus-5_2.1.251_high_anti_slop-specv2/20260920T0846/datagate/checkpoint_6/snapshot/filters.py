"""Column filters of the form ``<column>__<comparator>=<value>``."""

import operator
import time
from collections.abc import Callable
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from errors import ApiError
from store import Row

CONTROL_PREFIX = "_"
SEPARATOR = "__"
QUERY_BUDGET_SECONDS = 2.0

# A test applied to one stored cell value.
Matcher = Callable[[object], bool]


@dataclass(frozen=True)
class Filter:
    """One validated filter: which column to read and how to judge its value."""

    index: int
    matches: Matcher


def parse_filters(args: MultiDict, columns: list[str]) -> list[Filter]:
    """Turn every ``column__comparator`` parameter into a row test.

    Control parameters and plain names without a comparator suffix are not
    filters and pass through untouched; everything else must name a known
    column and a known comparator.
    """
    filters = []
    for key in args:
        if key.startswith(CONTROL_PREFIX) or SEPARATOR not in key:
            continue
        if len(args.getlist(key)) > 1:
            raise ApiError(f"Filter {key!r} may only be given once", 400)

        column, _, comparator = key.rpartition(SEPARATOR)
        if comparator not in COMPARATORS:
            raise ApiError(f"Filter {key!r} uses an unknown comparator: {comparator!r}", 400)
        if column not in columns:
            raise ApiError(f"Filter {key!r} names no column: {column!r}", 400)
        filters.append(Filter(columns.index(column), COMPARATORS[comparator](args[key], key)))
    return filters


def apply_filters(rows: list[Row], filters: list[Filter]) -> list[Row]:
    """Keep the rows satisfying every filter, within the query time budget.

    The scan is the part of a query that grows with both the row count and the
    number of filters, so it carries the deadline: a scan that outlives its
    budget is reported as a bad request instead of being left to run.
    """
    if not filters:
        return rows

    expiry = time.perf_counter() + QUERY_BUDGET_SECONDS
    kept = []
    for row in rows:
        if time.perf_counter() > expiry:
            raise ApiError("Query timed out; narrow the filters and retry", 400)
        if all(test.matches(row.values[test.index]) for test in filters):
            kept.append(row)
    return kept


# Each comparator builds its matcher from the filter value and the parameter
# name it came from, the latter naming the offending filter in error messages.


def _exact(wanted: str, key: str) -> Matcher:
    return lambda stored: str(stored) == wanted


def _contains(wanted: str, key: str) -> Matcher:
    return lambda stored: wanted in str(stored)


def _less(wanted: str, key: str) -> Matcher:
    return _numeric(operator.lt, wanted, key)


def _greater(wanted: str, key: str) -> Matcher:
    return _numeric(operator.gt, wanted, key)


def _numeric(compare, wanted: str, key: str) -> Matcher:
    """Compare stored values as floats; values that do not parse never match."""
    threshold = _as_float(wanted)
    if threshold is None:
        raise ApiError(f"Filter {key!r} needs a numeric value, got {wanted!r}", 400)

    def matches(stored) -> bool:
        number = _as_float(stored)
        return number is not None and compare(number, threshold)

    return matches


def _as_float(value) -> float | None:
    """Read a stored or filter value as a float, or ``None`` when it is text."""
    try:
        return float(value)
    except ValueError:
        return None


COMPARATORS = {"exact": _exact, "contains": _contains, "less": _less, "greater": _greater}

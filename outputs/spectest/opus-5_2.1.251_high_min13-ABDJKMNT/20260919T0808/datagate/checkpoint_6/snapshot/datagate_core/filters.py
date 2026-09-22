"""Column filters of `GET /datasets/<id>`, in the form `<column>__<comparator>=<value>`."""

import operator
from collections.abc import Callable
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from datagate_core.errors import InvalidRequestError
from datagate_core.tables import NumberedRow
from datagate_core.timing import Deadline
from datagate_core.values import Value, as_number, as_text

#: Separates the column from the comparator; the comparator is the final segment (T26).
SEPARATOR = "__"
#: Names starting with this belong to the control namespace and never filter.
CONTROL_PREFIX = "_"

#: Comparators reading both sides as text, on the textual form of the cell (T25).
TEXT_COMPARATORS = {
    "exact": lambda stored, wanted: stored == wanted,
    "contains": lambda stored, wanted: wanted in stored,
}
#: Comparators reading both sides as floats; non-numeric cells match neither.
NUMERIC_COMPARATORS = {"less": operator.lt, "greater": operator.gt}
COMPARATORS = (*TEXT_COMPARATORS, *NUMERIC_COMPARATORS)


@dataclass(frozen=True)
class Filter:
    """One parsed condition: the column it reads and the test its cells must pass."""

    index: int
    matches: Callable[[Value], bool]

    def accepts(self, row: list[Value]) -> bool:
        """True when this row's cell in the filtered column passes the test."""
        return self.matches(row[self.index])


def parse_filters(args: MultiDict, columns: list[str]) -> list[Filter]:
    """Read every filter parameter of a dataset request, rejecting invalid ones."""
    return [_parse(key, args, columns) for key in args if _is_filter(key)]


def select(rows: list[NumberedRow], filters: list[Filter], deadline: Deadline) -> list[NumberedRow]:
    """Keep the rows passing every filter - filters are ANDed - within the time budget."""
    kept = []
    for numbered in rows:
        deadline.check()
        if all(condition.accepts(numbered[1]) for condition in filters):
            kept.append(numbered)
    return kept


def _is_filter(key: str) -> bool:
    """Filter keys carry a separator and stay out of the control namespace (T28, T33)."""
    return SEPARATOR in key and not key.startswith(CONTROL_PREFIX)


def _parse(key: str, args: MultiDict, columns: list[str]) -> Filter:
    """Validate one filter key against the table, returning the condition it denotes."""
    if len(args.getlist(key)) > 1:
        raise InvalidRequestError(f"filter {key!r} must not be repeated")

    column, comparator = key.rsplit(SEPARATOR, 1)
    if comparator not in COMPARATORS:
        raise InvalidRequestError(
            f"unknown comparator {comparator!r}; expected one of {', '.join(COMPARATORS)}"
        )
    if column not in columns:
        raise InvalidRequestError(f"filter names an unknown column: {column!r}")
    return Filter(index=columns.index(column), matches=_test(comparator, args[key]))


def _test(comparator: str, wanted: str) -> Callable[[Value], bool]:
    """Bind a comparator to its filter value, giving a test on one stored cell."""
    if comparator in NUMERIC_COMPARATORS:
        ordering = NUMERIC_COMPARATORS[comparator]
        threshold = _threshold(comparator, wanted)
        return lambda stored: _ordered(stored, ordering, threshold)

    compare = TEXT_COMPARATORS[comparator]
    return lambda stored: compare(as_text(stored), wanted)


def _threshold(comparator: str, wanted: str) -> float:
    """The filter side of a numeric comparison, which has to parse as a float (T31)."""
    number = as_number(wanted)
    if number is None:
        raise InvalidRequestError(
            f"'__{comparator}' needs a numeric value, got {wanted!r}"
        )
    return number


def _ordered(stored: Value, ordering: Callable[[float, float], bool], threshold: float) -> bool:
    """Compare a cell numerically; cells that are not numbers match nothing."""
    number = as_number(stored)
    return number is not None and ordering(number, threshold)

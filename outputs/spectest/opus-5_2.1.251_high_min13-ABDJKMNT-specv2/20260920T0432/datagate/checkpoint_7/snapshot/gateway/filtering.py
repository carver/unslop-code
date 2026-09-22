"""Column filters of the form `<column>__<comparator>=<value>`.

`parse_filters` validates the filter parameters of a request against a dataset's
columns; `matches` then tests one row against the parsed conditions.
"""

from dataclasses import dataclass
from typing import Callable

from .errors import ApiError
from .tabular import Cell

CONTROL_PREFIX = "_"
SEPARATOR = "__"


def _exact(cell: Cell, value: str) -> bool:
    """Whole-value string equality against the cell as the response renders it."""
    return str(cell) == value


def _contains(cell: Cell, value: str) -> bool:
    return value in str(cell)


def _less(cell: Cell, bound: float) -> bool:
    number = as_number(cell)
    return number is not None and number < bound


def _greater(cell: Cell, bound: float) -> bool:
    number = as_number(cell)
    return number is not None and number > bound


COMPARATORS: dict[str, Callable[[Cell, str | float], bool]] = {
    "exact": _exact,
    "contains": _contains,
    "less": _less,
    "greater": _greater,
}
# The comparators that read both sides as numbers rather than as text.
NUMERIC_COMPARATORS = ("less", "greater")


@dataclass(frozen=True)
class Filter:
    """One parsed condition: which column to read, how to test it, against what."""

    index: int
    test: Callable[[Cell, str | float], bool]
    value: str | float


def parse_filters(args, columns: list[str]) -> list[Filter]:
    """Validate the filter parameters in `args` against a dataset's `columns`.

    Raises `ApiError(400)` on a repeated filter key, an unknown comparator or
    column, and a non-numeric value for a numeric comparator. Parameters that
    are controls or carry no comparator are not filters and are left alone.
    """
    filters = []
    for name, values in args.lists():
        if name.startswith(CONTROL_PREFIX) or SEPARATOR not in name:
            continue
        if len(values) > 1:
            raise ApiError(400, f"filter '{name}' was given more than once")
        filters.append(_build(name, values[0], columns))
    return filters


def matches(row: list[Cell], filters: list[Filter]) -> bool:
    """Whether `row` satisfies every filter."""
    return all(one.test(row[one.index], one.value) for one in filters)


def as_number(value: Cell) -> float | None:
    """`value` parsed as a float, or `None` when it is not numeric."""
    try:
        return float(value)
    except ValueError:
        return None


def _build(name: str, value: str, columns: list[str]) -> Filter:
    """Turn one `<column>__<comparator>=<value>` parameter into a `Filter`.

    The rightmost separator splits the name, so a column whose own name contains
    `__` stays filterable.
    """
    column, _, comparator = name.rpartition(SEPARATOR)
    if comparator not in COMPARATORS:
        raise ApiError(400, f"filter '{name}' uses an unknown comparator: '{comparator}'")
    if column not in columns:
        raise ApiError(400, f"filter '{name}' names an unknown column: '{column}'")
    return Filter(
        index=columns.index(column),
        test=COMPARATORS[comparator],
        value=_comparison_value(name, comparator, value),
    )


def _comparison_value(name: str, comparator: str, value: str) -> str | float:
    """The filter value as the comparator reads it: a number, or text as given."""
    if comparator not in NUMERIC_COMPARATORS:
        return value
    number = as_number(value)
    if number is None:
        raise ApiError(400, f"'{name}' needs a numeric value, got '{value}'")
    return number

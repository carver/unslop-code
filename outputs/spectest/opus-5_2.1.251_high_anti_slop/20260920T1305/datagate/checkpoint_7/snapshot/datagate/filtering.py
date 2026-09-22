"""Parsing and application of the ``/datasets`` column filters.

A filter is a query parameter named ``<column>__<comparator>``, whose value is the
target the column's cells are compared against. Control parameters (those starting with
``_``) and parameters without a ``__`` suffix are not filters. Several filters are
combined with AND.
"""

from collections.abc import Callable
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from .errors import DataGateError
from .store import Dataset
from .timing import Deadline
from .values import Value

Predicate = Callable[[Value], bool]
NumberedRow = tuple[int, list[Value]]


@dataclass(frozen=True)
class Filter:
    """One parsed filter: the column to read and the test its cell must pass."""

    column: str
    test: Predicate


def _as_number(value: Value) -> float | None:
    """Return ``value`` as a float, or ``None`` when it does not read as one."""
    try:
        return float(value)
    except ValueError:
        return None


def _numeric_target(comparator: str, raw: str) -> float:
    """Return the number ``comparator`` compares against, rejecting non-numeric text."""
    target = _as_number(raw)
    if target is None:
        raise DataGateError(
            f"comparator {comparator!r} needs a numeric value, got {raw!r}", 400
        )
    return target


def _exact(raw: str) -> Predicate:
    """Match cells whose text is exactly ``raw``."""
    return lambda cell: str(cell) == raw


def _contains(raw: str) -> Predicate:
    """Match cells whose text contains ``raw``."""
    return lambda cell: raw in str(cell)


def _less(raw: str) -> Predicate:
    """Match cells that read as a number strictly below ``raw``."""
    target = _numeric_target("less", raw)

    def test(cell: Value) -> bool:
        number = _as_number(cell)
        return number is not None and number < target

    return test


def _greater(raw: str) -> Predicate:
    """Match cells that read as a number strictly above ``raw``."""
    target = _numeric_target("greater", raw)

    def test(cell: Value) -> bool:
        number = _as_number(cell)
        return number is not None and number > target

    return test


COMPARATORS: dict[str, Callable[[str], Predicate]] = {
    "exact": _exact,
    "contains": _contains,
    "less": _less,
    "greater": _greater,
}


def read_filters(args: MultiDict[str, str], columns: list[str]) -> list[Filter]:
    """Read every filter parameter in a query string, in the order it appears.

    Columns are matched exactly against ``columns``, the dataset's column names. An
    unknown column, an unknown comparator and a repeated filter each raise a 400 error.
    """
    filters = []
    for key in args.keys():
        if key.startswith("_") or "__" not in key:
            continue
        values = args.getlist(key)
        if len(values) > 1:
            raise DataGateError(f"filter {key!r} must not be repeated", 400)
        filters.append(_read_filter(key, values[0], columns))
    return filters


def _read_filter(key: str, raw: str, columns: list[str]) -> Filter:
    """Turn the parameter ``key=raw`` into a filter on one of ``columns``."""
    column, _, comparator = key.rpartition("__")
    if comparator not in COMPARATORS:
        listed = " or ".join(repr(name) for name in COMPARATORS)
        raise DataGateError(
            f"filter {key!r} needs a comparator of {listed}, got {comparator!r}", 400
        )
    if column not in columns:
        raise DataGateError(f"cannot filter on unknown column {column!r}", 400)
    return Filter(column=column, test=COMPARATORS[comparator](raw))


def matching_rows(
    dataset: Dataset, filters: list[Filter], deadline: Deadline
) -> list[NumberedRow]:
    """Number the dataset's rows from 1 and keep those passing every filter.

    Numbering happens before filtering, so a kept row still reports the position it has
    in the source file. The scan gives up with a 400 error once ``deadline`` passes.
    """
    tests = [(dataset.columns.index(item.column), item.test) for item in filters]
    kept = []
    for rowid, row in enumerate(dataset.rows, start=1):
        deadline.check()
        if all(test(row[position]) for position, test in tests):
            kept.append((rowid, row))
    return kept

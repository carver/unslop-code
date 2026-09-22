"""Column filters of ``GET /datasets/<id>``: ``<column>__<comparator>=<value>``."""

from collections.abc import Callable
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from gateway.errors import GateError
from gateway.values import Value

#: Separates the column name from the comparator in a filter parameter name.
SEPARATOR = "__"
#: Parameters starting with this are control parameters, never filters.
CONTROL_PREFIX = "_"


def exact(cell: Value, target: Value) -> bool:
    """Case-sensitive equality between the cell's text and the filter value."""
    return str(cell) == target


def contains(cell: Value, target: Value) -> bool:
    """Case-sensitive substring test against the cell's text."""
    return target in str(cell)


def less(cell: Value, target: Value) -> bool:
    """Strict numeric ``<``; a cell that is not a number matches nothing."""
    number = as_number(cell)
    return number is not None and number < target


def greater(cell: Value, target: Value) -> bool:
    """Strict numeric ``>``; a cell that is not a number matches nothing."""
    number = as_number(cell)
    return number is not None and number > target


COMPARATORS: dict[str, Callable[[Value, Value], bool]] = {
    "exact": exact,
    "contains": contains,
    "less": less,
    "greater": greater,
}
#: Comparators whose filter value has to be read as a number.
NUMERIC_COMPARATORS = ("less", "greater")


@dataclass(frozen=True)
class Filter:
    """One resolved condition: a column position, a value and how to compare."""

    index: int
    target: Value
    test: Callable[[Value, Value], bool]

    def matches(self, row: list[Value]) -> bool:
        """Report whether ``row`` satisfies this condition.

        A row parsed from a ragged source may not reach ``index``; the missing
        cell is read as empty text rather than excluding the row outright.
        """
        cell = row[self.index] if self.index < len(row) else ""
        return self.test(cell, self.target)


def parse_filters(args: MultiDict, columns: list[str]) -> list[Filter]:
    """Resolve every filter parameter of a request against ``columns``.

    Control parameters and parameters carrying no ``__`` are not filters and
    are left alone; everything else has to name a column and a comparator.
    """
    return [
        build_filter(name, values, columns)
        for name, values in args.lists()
        if not name.startswith(CONTROL_PREFIX) and SEPARATOR in name
    ]


def build_filter(name: str, values: list[str], columns: list[str]) -> Filter:
    """Turn one ``<column>__<comparator>`` parameter into a :class:`Filter`.

    The comparator is the part after the last ``__``, so columns whose own
    name contains the separator stay addressable.
    """
    if len(values) > 1:
        raise GateError(f"Filter parameter {name!r} may be given only once", 400)

    column, _, comparator = name.rpartition(SEPARATOR)
    if comparator not in COMPARATORS:
        raise GateError(
            f"Unknown filter comparator: {comparator!r}; "
            f"expected one of {', '.join(COMPARATORS)}",
            400,
        )
    if column not in columns:
        raise GateError(f"Unknown filter column: {column!r}", 400)

    raw = values[0]
    target = to_number(raw, name) if comparator in NUMERIC_COMPARATORS else raw
    return Filter(
        index=columns.index(column), target=target, test=COMPARATORS[comparator]
    )


def to_number(raw: str, name: str) -> float:
    """Read the value of a numeric filter, rejecting anything unparsable."""
    try:
        return float(raw)
    except ValueError as exc:
        raise GateError(
            f"Filter parameter {name!r} needs a numeric value, got {raw!r}", 400
        ) from exc


def as_number(cell: Value) -> float | None:
    """Return a stored cell as a float, or ``None`` when its text is not numeric."""
    try:
        return float(cell)
    except ValueError:
        return None

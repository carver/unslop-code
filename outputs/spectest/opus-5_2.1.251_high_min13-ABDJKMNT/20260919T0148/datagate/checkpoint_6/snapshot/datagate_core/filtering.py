"""Column filters of `/datasets/<id>`: `<column>__<comparator>=<value>`."""

from dataclasses import dataclass

from .errors import DatagateError

SEPARATOR = "__"
CONTROL_PREFIX = "_"


@dataclass(frozen=True)
class Filter:
    """One validated filter, bound to the position of its column in a table."""

    position: int
    comparator: str
    text: str
    number: float | None


def parse_filters(args, columns):
    """Read every filter parameter in `args`, validated against a table's `columns`.

    Parameters named like a control (`_size`) and parameters carrying no `__`
    are not filters and are left alone. Raises a 400 `DatagateError` for a
    repeated key, an unknown column or comparator, and for a non-numeric value
    given to a numeric comparator.
    """
    return [_filter(key, args, columns) for key in args if _is_filter(key)]


def matches(values, filters):
    """True when a row's `values` satisfy every filter, which is how filters AND."""
    return all(COMPARATORS[spec.comparator](values[spec.position], spec) for spec in filters)


def _is_filter(key):
    return not key.startswith(CONTROL_PREFIX) and SEPARATOR in key


def _filter(key, args, columns):
    """Validate one `<column>__<comparator>` parameter into a `Filter`.

    The key splits at its last `__`, so a column name may itself contain the
    separator; what remains must name a column exactly.
    """
    if len(args.getlist(key)) > 1:
        raise DatagateError(400, f"Filter '{key}' must not be repeated.")

    column, comparator = key.rsplit(SEPARATOR, 1)
    if comparator not in COMPARATORS:
        raise DatagateError(
            400,
            f"Unknown comparator {comparator!r} in filter '{key}'; "
            "expected 'exact', 'contains', 'less' or 'greater'.",
        )
    if column not in columns:
        raise DatagateError(400, f"Unknown filter column: {column!r}.")

    value = args[key]
    return Filter(columns.index(column), comparator, value, _filter_number(key, comparator, value))


def _filter_number(key, comparator, value):
    """Parse the value a numeric comparator compares against; text filters get None."""
    if comparator not in NUMERIC_COMPARATORS:
        return None
    number = _number(value)
    if number is None:
        raise DatagateError(400, f"Filter '{key}' needs a numeric value, got {value!r}.")
    return number


def _number(value):
    """Return `value` as a float, or None when it is not a number to compare."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exact(stored, spec):
    return str(stored) == spec.text


def _contains(stored, spec):
    return spec.text in str(stored)


def _less(stored, spec):
    stored_number = _number(stored)
    return stored_number is not None and stored_number < spec.number


def _greater(stored, spec):
    stored_number = _number(stored)
    return stored_number is not None and stored_number > spec.number


COMPARATORS = {
    "exact": _exact,
    "contains": _contains,
    "less": _less,
    "greater": _greater,
}
NUMERIC_COMPARATORS = ("less", "greater")

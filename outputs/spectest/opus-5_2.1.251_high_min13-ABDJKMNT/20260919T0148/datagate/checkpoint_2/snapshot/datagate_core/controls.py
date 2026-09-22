"""Control parameters of `/datasets/<id>`: pagination, sorting and response shape."""

import re
from dataclasses import dataclass

from .errors import DatagateError

DEFAULT_SIZE = 100
DEFAULT_OFFSET = 0
DEFAULT_SHAPE = "lists"
SHAPES = ("lists", "objects")
HIDE = "hide"

# Sizes and offsets are matched as whole integer literals so that `1.5`, `1_0` and
# stray whitespace are rejected rather than silently rounded or accepted.
INTEGER = re.compile(r"[+-]?[0-9]+\Z")


@dataclass(frozen=True)
class Controls:
    """The validated controls for one dataset request."""

    size: int
    offset: int
    sort_column: str | None
    descending: bool
    shape: str
    show_rowid: bool
    show_total: bool


def parse_controls(args, columns):
    """Read the control parameters from `args`, validated against a table's `columns`.

    Raises a 400 `DatagateError` for a repeated, malformed or out-of-range value.
    Every control is read even when another has already decided the outcome, so a
    repeat is rejected wherever it appears.
    """
    sort_column, descending = _sort_order(args, columns)
    return Controls(
        size=_bounded_int(args, "_size", DEFAULT_SIZE, 1, "a positive integer"),
        offset=_bounded_int(args, "_offset", DEFAULT_OFFSET, 0, "a non-negative integer"),
        sort_column=sort_column,
        descending=descending,
        shape=_shape(args),
        show_rowid=not _hidden(args, "_rowid"),
        show_total=not _hidden(args, "_total"),
    )


def _single(args, name):
    """Return the one value given for `name`, or None when absent; a repeat is a 400."""
    values = args.getlist(name)
    if len(values) > 1:
        raise DatagateError(400, f"Query parameter '{name}' must not be repeated.")
    return values[0] if values else None


def _bounded_int(args, name, default, minimum, requirement):
    """Read an integer parameter of at least `minimum`, falling back to `default`."""
    raw = _single(args, name)
    if raw is None:
        return default
    if not INTEGER.match(raw) or int(raw) < minimum:
        raise DatagateError(400, f"Query parameter '{name}' must be {requirement}, got {raw!r}.")
    return int(raw)


def _shape(args):
    """Read `_shape`, which names the row rendering and defaults to `lists`."""
    value = _single(args, "_shape")
    if value is None:
        return DEFAULT_SHAPE
    if value not in SHAPES:
        raise DatagateError(
            400, f"Query parameter '_shape' must be 'lists' or 'objects', got {value!r}."
        )
    return value


def _hidden(args, name):
    """True when the visibility toggle `name` is set; only `hide` is a legal value."""
    value = _single(args, name)
    if value is None:
        return False
    if value != HIDE:
        raise DatagateError(
            400, f"Query parameter '{name}' accepts only '{HIDE}', got {value!r}."
        )
    return True


def _sort_order(args, columns):
    """Return the column to sort on and whether to descend, or `(None, False)`.

    `_sort_desc` outranks `_sort` when both are given; only the winning column is
    checked against `columns`, since the other has no effect on the response.
    """
    ascending = _single(args, "_sort")
    descending = _single(args, "_sort_desc")

    column = ascending if descending is None else descending
    if column is None:
        return None, False
    if not column:
        raise DatagateError(400, "Sort column must not be empty.")
    if column not in columns:
        raise DatagateError(400, f"Unknown sort column: {column!r}.")
    return column, descending is not None

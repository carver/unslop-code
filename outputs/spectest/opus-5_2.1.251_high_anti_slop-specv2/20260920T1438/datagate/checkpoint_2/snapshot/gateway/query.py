"""Control parameters of ``GET /datasets/<id>``: pagination, sorting and shape."""

import re
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from gateway.errors import GateError

DEFAULT_SIZE = 100
LISTS, OBJECTS = "lists", "objects"
SHAPES = (LISTS, OBJECTS)
HIDE = "hide"
CONTROLS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")

INTEGER = re.compile(r"[+-]?\d+\Z")


@dataclass(frozen=True)
class Query:
    """The resolved reading instructions for one dataset request."""

    size: int
    offset: int
    shape: str
    sort: str | None
    descending: bool
    show_rowid: bool
    show_total: bool


def parse_query(args: MultiDict, columns: list[str]) -> Query:
    """Read the control parameters of a request against a table of ``columns``."""
    given = {name: single_value(args, name) for name in CONTROLS}
    column, descending = sort_order(given["_sort"], given["_sort_desc"], columns)
    return Query(
        size=bounded_int(given["_size"], "_size", default=DEFAULT_SIZE, minimum=1),
        offset=bounded_int(given["_offset"], "_offset", default=0, minimum=0),
        shape=shape(given["_shape"]),
        sort=column,
        descending=descending,
        show_rowid=not hides(given["_rowid"], "_rowid"),
        show_total=not hides(given["_total"], "_total"),
    )


def single_value(args: MultiDict, name: str) -> str | None:
    """Return the one value given for ``name``, or ``None`` when it is absent."""
    given = args.getlist(name)
    if len(given) > 1:
        raise GateError(f"Query parameter {name!r} may be given only once", 400)
    return given[0] if given else None


def bounded_int(raw: str | None, name: str, default: int, minimum: int) -> int:
    """Read an integer control parameter, rejecting values below ``minimum``."""
    if raw is None:
        return default
    if not INTEGER.match(raw) or int(raw) < minimum:
        raise GateError(
            f"Query parameter {name!r} must be an integer >= {minimum}", 400
        )
    return int(raw)


def shape(raw: str | None) -> str:
    """Return the requested row shape, defaulting to ``lists``."""
    if raw is None:
        return LISTS
    if raw not in SHAPES:
        raise GateError(
            f"Query parameter '_shape' must be one of {' or '.join(SHAPES)}", 400
        )
    return raw


def hides(raw: str | None, name: str) -> bool:
    """Report whether a visibility toggle asks for its field to be dropped."""
    if raw is None:
        return False
    if raw != HIDE:
        raise GateError(f"Query parameter {name!r} accepts only {HIDE!r}", 400)
    return True


def sort_order(
    ascending: str | None, descending: str | None, columns: list[str]
) -> tuple[str | None, bool]:
    """Resolve the sort column and its direction; ``_sort_desc`` wins over ``_sort``.

    Returns ``(None, False)`` when neither parameter is present. An empty value
    names no column and is therefore rejected like any other unknown one.
    """
    column = descending if descending is not None else ascending
    if column is None:
        return None, False
    if column not in columns:
        raise GateError(f"Unknown sort column: {column!r}", 400)
    return column, descending is not None

"""Validation and application of the ``_``-prefixed dataset query controls."""

from dataclasses import dataclass
import re

from werkzeug.datastructures import MultiDict

from errors import ApiError
from store import Row

CONTROLS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")
DEFAULT_SIZE = 100
LISTS, OBJECTS = "lists", "objects"
HIDE = "hide"

INTEGER = re.compile(r"\d+")


@dataclass(frozen=True)
class Controls:
    """A validated request: which rows to return, in what order and what shape.

    ``sort_index`` is the position of the sort column in the dataset's columns,
    already resolved from the ``_sort``/``_sort_desc`` name, or ``None`` when
    the source order stands.
    """

    size: int
    offset: int
    shape: str
    sort_index: int | None
    descending: bool
    show_rowid: bool
    show_total: bool


def parse_controls(args: MultiDict, columns: list[str]) -> Controls:
    """Read the control parameters of a dataset request, rejecting bad values."""
    for name in CONTROLS:
        if len(args.getlist(name)) > 1:
            raise ApiError(f"Query parameter {name!r} may only be given once", 400)

    sort_column, descending = _ordering(args, columns)
    return Controls(
        size=_whole_number(args, "_size", DEFAULT_SIZE, minimum=1),
        offset=_whole_number(args, "_offset", 0, minimum=0),
        shape=_shape(args),
        sort_index=None if sort_column is None else columns.index(sort_column),
        descending=descending,
        show_rowid=_shown(args, "_rowid"),
        show_total=_shown(args, "_total"),
    )


def select(rows: list[Row], controls: Controls) -> list[Row]:
    """Order the rows, then cut the requested window out of the result.

    Sorting comes first so pagination walks the sorted sequence, and it runs on
    the whole list at once, which keeps rows with equal keys in source order.
    """
    ordered = rows
    if controls.sort_index is not None:
        ordered = sorted(
            rows,
            key=lambda row: _comparable(row.values[controls.sort_index]),
            reverse=controls.descending,
        )
    return ordered[controls.offset : controls.offset + controls.size]


def render(rows: list[Row], columns: list[str], controls: Controls) -> list:
    """Present rows as bare value arrays or as column-keyed objects."""
    if controls.shape == LISTS:
        return [row.values for row in rows]
    if controls.show_rowid:
        return [{"rowid": row.rowid} | dict(zip(columns, row.values)) for row in rows]
    return [dict(zip(columns, row.values)) for row in rows]


def _whole_number(args: MultiDict, name: str, default: int, minimum: int) -> int:
    raw = args.get(name)
    if raw is None:
        return default
    if not INTEGER.fullmatch(raw) or int(raw) < minimum:
        wanted = "a positive integer" if minimum else "a non-negative integer"
        raise ApiError(f"Query parameter {name!r} must be {wanted}", 400)
    return int(raw)


def _shape(args: MultiDict) -> str:
    shape = args.get("_shape", LISTS)
    if shape not in (LISTS, OBJECTS):
        raise ApiError(f"Query parameter '_shape' must be {LISTS!r} or {OBJECTS!r}", 400)
    return shape


def _ordering(args: MultiDict, columns: list[str]) -> tuple[str | None, bool]:
    """Resolve the sort column and direction; ``_sort_desc`` outranks ``_sort``."""
    column, descending = None, False
    for name, reverse in (("_sort", False), ("_sort_desc", True)):
        requested = args.get(name)
        if requested is None:
            continue
        if requested not in columns:
            raise ApiError(f"Query parameter {name!r} names no column: {requested!r}", 400)
        column, descending = requested, reverse
    return column, descending


def _shown(args: MultiDict, name: str) -> bool:
    """Report whether a field survives its toggle, which only accepts ``hide``."""
    value = args.get(name)
    if value is None:
        return True
    if value != HIDE:
        raise ApiError(f"Query parameter {name!r} only accepts {HIDE!r}", 400)
    return False


def _comparable(value):
    """Rank numbers ahead of text so a column holding both still sorts."""
    return (isinstance(value, str), value)

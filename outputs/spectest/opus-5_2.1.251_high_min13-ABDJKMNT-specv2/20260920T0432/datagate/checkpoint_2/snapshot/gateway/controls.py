"""Query controls for a dataset read: pagination, sorting and response shape.

`parse_controls` turns the raw query string into a validated `Controls`, and
`select_rows`/`render_rows` apply it: sort, then paginate, then shape.
"""

import re
from dataclasses import dataclass

from .errors import ApiError
from .tabular import Cell

CONTROL_PARAMS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")
DEFAULT_SIZE = 100
SHAPE_LISTS = "lists"
SHAPE_OBJECTS = "objects"
SHAPES = (SHAPE_LISTS, SHAPE_OBJECTS)
HIDE = "hide"

# The header is source row 1, so the first data row is row 2.
FIRST_DATA_ROWID = 2

DIGITS = re.compile(r"[0-9]+")

NumberedRow = tuple[int, list[Cell]]


@dataclass(frozen=True)
class Controls:
    """The validated control parameters of one `/datasets/<id>` request."""

    size: int
    offset: int
    shape: str
    sort_index: int | None
    descending: bool
    show_rowid: bool
    show_total: bool


def parse_controls(args, columns: list[str]) -> Controls:
    """Validate the control parameters in `args` against a dataset's `columns`.

    Raises `ApiError(400)` on a repeated control, an unusable value, or a sort
    column the dataset does not have.
    """
    _reject_repeats(args)
    sort_index, descending = _sort_order(args, columns)
    return Controls(
        size=_count(args, "_size", default=DEFAULT_SIZE, minimum=1, kind="a positive integer"),
        offset=_count(args, "_offset", default=0, minimum=0, kind="a non-negative integer"),
        shape=_shape(args),
        sort_index=sort_index,
        descending=descending,
        show_rowid=_is_shown(args, "_rowid"),
        show_total=_is_shown(args, "_total"),
    )


def select_rows(rows: list[list[Cell]], controls: Controls) -> list[NumberedRow]:
    """Sort and paginate `rows`, keeping every row paired with its source rowid.

    Sorting runs over the whole dataset before the window is cut, and is stable,
    so rows tied on the sort column stay in source order in both directions.
    """
    numbered = list(enumerate(rows, start=FIRST_DATA_ROWID))
    if controls.sort_index is not None:
        numbered.sort(
            key=lambda numbered_row: _sort_key(numbered_row[1][controls.sort_index]),
            reverse=controls.descending,
        )
    return numbered[controls.offset : controls.offset + controls.size]


def render_rows(numbered: list[NumberedRow], columns: list[str], controls: Controls) -> list:
    """Render a window as bare arrays, or as objects keyed by column name."""
    if controls.shape == SHAPE_LISTS:
        return [row for _, row in numbered]
    return [_as_object(rowid, row, columns, controls.show_rowid) for rowid, row in numbered]


def _as_object(rowid: int, row: list[Cell], columns: list[str], show_rowid: bool) -> dict:
    """One row as an object; `rowid` leads it unless the caller hid it."""
    fields = {"rowid": rowid} if show_rowid else {}
    fields.update(zip(columns, row))
    return fields


def _sort_key(cell: Cell) -> tuple[int, float, str]:
    """Order a column that mixes types: numbers by value, then text by text."""
    if isinstance(cell, str):
        return (1, 0.0, cell)
    return (0, cell, "")


def _reject_repeats(args) -> None:
    for name in CONTROL_PARAMS:
        if len(args.getlist(name)) > 1:
            raise ApiError(400, f"control parameter '{name}' was given more than once")


def _count(args, name: str, default: int, minimum: int, kind: str) -> int:
    """Read a bare decimal count, rejecting anything outside `kind`'s range."""
    raw = args.get(name)
    if raw is None:
        return default
    if not DIGITS.fullmatch(raw) or int(raw) < minimum:
        raise ApiError(400, f"'{name}' must be {kind}, got '{raw}'")
    return int(raw)


def _shape(args) -> str:
    shape = args.get("_shape", SHAPE_LISTS)
    if shape not in SHAPES:
        raise ApiError(400, f"'_shape' must be 'lists' or 'objects', got '{shape}'")
    return shape


def _is_shown(args, name: str) -> bool:
    """Whether a toggled field stays in the response; only `hide` removes it."""
    value = args.get(name)
    if value is None:
        return True
    if value != HIDE:
        raise ApiError(400, f"'{name}' accepts only 'hide', got '{value}'")
    return False


def _sort_order(args, columns: list[str]) -> tuple[int | None, bool]:
    """Resolve the sort column, with `_sort_desc` taking precedence over `_sort`.

    Only the winning parameter is validated: the other one selects nothing, so
    its value never reaches a column lookup.
    """
    for name, descending in (("_sort_desc", True), ("_sort", False)):
        column = args.get(name)
        if column is None:
            continue
        if column not in columns:
            raise ApiError(400, f"'{name}' names an unknown column: '{column}'")
        return columns.index(column), descending
    return None, False

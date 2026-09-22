"""Validation of the `/datasets/<id>` control parameters.

Every control is optional; anything supplied has to be usable, so a rejected
value is reported as `HTTP 400` rather than silently falling back to a default.
"""

from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from .errors import DataGateError

CONTROL_PARAMETERS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")
SHAPES = ("lists", "objects")
HIDE = "hide"
DEFAULT_SIZE = 100
DEFAULT_OFFSET = 0


@dataclass(frozen=True)
class QueryControls:
    """How one request wants its rows paginated, sorted and shaped."""

    size: int
    offset: int
    shape: str
    sort_column: str | None
    descending: bool
    show_rowid: bool
    show_total: bool


def parse_controls(args: MultiDict, columns: list[str]) -> QueryControls:
    """Read the control parameters of a request against the dataset's `columns`."""
    _reject_repeats(args)
    sort_column, descending = _sort_order(args, columns)
    return QueryControls(
        size=_whole_number(args, "_size", DEFAULT_SIZE, minimum=1, requirement="a positive integer"),
        offset=_whole_number(args, "_offset", DEFAULT_OFFSET, minimum=0, requirement="a non-negative integer"),
        shape=_shape(args),
        sort_column=sort_column,
        descending=descending,
        show_rowid=_is_visible(args, "_rowid"),
        show_total=_is_visible(args, "_total"),
    )


def _reject_repeats(args: MultiDict) -> None:
    for name in CONTROL_PARAMETERS:
        if len(args.getlist(name)) > 1:
            raise DataGateError(f"Control parameter '{name}' must not be repeated", 400)


def _whole_number(args: MultiDict, name: str, default: int, minimum: int, requirement: str) -> int:
    raw = args.get(name)
    if raw is None:
        return default
    unusable = DataGateError(f"'{name}' must be {requirement}, got {raw!r}", 400)
    try:
        value = int(raw)
    except ValueError:
        raise unusable from None
    if value < minimum:
        raise unusable
    return value


def _shape(args: MultiDict) -> str:
    shape = args.get("_shape", SHAPES[0])
    if shape not in SHAPES:
        raise DataGateError(f"'_shape' must be one of {' or '.join(SHAPES)}, got {shape!r}", 400)
    return shape


def _is_visible(args: MultiDict, name: str) -> bool:
    """Toggles only ever hide: `hide` switches the field off, nothing else is a value."""
    raw = args.get(name)
    if raw is not None and raw != HIDE:
        raise DataGateError(f"'{name}' accepts only the value '{HIDE}', got {raw!r}", 400)
    return raw is None


def _sort_order(args: MultiDict, columns: list[str]) -> tuple[str | None, bool]:
    """Resolve the sort column and direction; `_sort_desc` wins when both are given."""
    for name in ("_sort", "_sort_desc"):
        column = args.get(name)
        if column is not None and (not column or column not in columns):
            raise DataGateError(f"'{name}' is not a column of this dataset: {column!r}", 400)
    descending = "_sort_desc" in args
    return args.get("_sort_desc") if descending else args.get("_sort"), descending

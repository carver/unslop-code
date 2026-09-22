"""Parsing and validating the control parameters of `GET /datasets/<id>`."""

from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from datagate_core.errors import InvalidRequestError

#: Parameters the spec forbids repeating (`limit` is the pre-`_size` spelling).
CONTROL_PARAMETERS = ("_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total")
SORT_PARAMETERS = ("_sort", "_sort_desc")
SIZE_PARAMETERS = ("_size", "limit")

LISTS = "lists"
OBJECTS = "objects"
SHAPES = (LISTS, OBJECTS)

DEFAULT_SIZE = 100
HIDE = "hide"


@dataclass(frozen=True)
class Controls:
    """The validated pagination, sorting and shape settings of one query."""

    size: int = DEFAULT_SIZE
    offset: int = 0
    sort_column: str | None = None
    descending: bool = False
    shape: str = LISTS
    show_rowid: bool = True
    show_total: bool = True


def parse_controls(args: MultiDict, columns: list[str]) -> Controls:
    """Read the control parameters of a dataset request, rejecting invalid ones."""
    _reject_repeats(args)
    sort_column, descending = _sort_order(args, columns)
    return Controls(
        size=_size(args),
        offset=_integer(
            args, "_offset", default=0, minimum=0, wording="a non-negative integer"
        ),
        sort_column=sort_column,
        descending=descending,
        shape=_shape(args),
        show_rowid=_visible(args, "_rowid"),
        show_total=_visible(args, "_total"),
    )


def _reject_repeats(args: MultiDict) -> None:
    """A control parameter given more than once is a client error, whatever its value."""
    repeated = [name for name in CONTROL_PARAMETERS if len(args.getlist(name)) > 1]
    if repeated:
        raise InvalidRequestError(f"query parameter {repeated[0]!r} must not be repeated")


def _size(args: MultiDict) -> int:
    """Rows per page: `_size`, else the deprecated `limit` alias, else 100 (see T11)."""
    given = next((name for name in SIZE_PARAMETERS if name in args), None)
    if given is None:
        return DEFAULT_SIZE
    return _integer(args, given, default=DEFAULT_SIZE, minimum=1, wording="a positive integer")


def _integer(args: MultiDict, name: str, default: int, minimum: int, wording: str) -> int:
    """Read a bounded integer parameter, accepting plain digit strings only (T20)."""
    raw = args.get(name)
    if raw is None:
        return default
    if not raw.isdigit() or int(raw) < minimum:
        raise InvalidRequestError(f"'{name}' must be {wording}, got {raw!r}")
    return int(raw)


def _sort_order(args: MultiDict, columns: list[str]) -> tuple[str | None, bool]:
    """Resolve the sort column and direction; `_sort_desc` wins when both are given."""
    for name in SORT_PARAMETERS:
        if name in args:
            _validate_column(name, args[name], columns)
    descending = "_sort_desc" in args
    return (args["_sort_desc"] if descending else args.get("_sort")), descending


def _validate_column(name: str, column: str, columns: list[str]) -> None:
    """Every sort parameter present must name a column of this table (T18, T21)."""
    if not column:
        raise InvalidRequestError(f"'{name}' requires a column name")
    if column not in columns:
        raise InvalidRequestError(f"'{name}' names an unknown column: {column!r}")


def _shape(args: MultiDict) -> str:
    """Read `_shape`, which is one of the two spelled-out shapes or an error."""
    shape = args.get("_shape", LISTS)
    if shape not in SHAPES:
        raise InvalidRequestError(f"'_shape' must be 'lists' or 'objects', got {shape!r}")
    return shape


def _visible(args: MultiDict, name: str) -> bool:
    """Read a visibility toggle: absent keeps the field, `hide` drops it, else 400."""
    if name not in args:
        return True
    if args[name] != HIDE:
        raise InvalidRequestError(f"'{name}' accepts only 'hide', got {args[name]!r}")
    return False

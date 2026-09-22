"""What every reader yields, and how typed values reach the caster.

Readers hand the rest of the tool :class:`Record` objects: the field names the
record itself carries, the matching cells, and the position used in error
messages. A cell is either the text a delimited input held, or a
:class:`JsonValue` wrapping the value a JSON-shaped source (JSON Lines, or a
nested parquet column) already decoded. Scalars of a typed source are rendered
to text here, so that one set of cast rules serves every format.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterator, NamedTuple

from .casting import render_timestamp


class JsonValue(NamedTuple):
    """A cell that arrived as a decoded JSON value rather than as text."""

    value: object


class Record(NamedTuple):
    """One input row: its own field names, its cells, and where it came from."""

    names: tuple[str, ...]
    #: ``None`` marks a missing cell; the reader has already applied the
    #: nullness rule of its own dialect.
    values: list[str | JsonValue | None]
    #: Line number, or row ordinal for parquet, used in error messages.
    position: int


class RecordStream(NamedTuple):
    """The records of one input, plus the columns it declares up front.

    ``names`` is empty for JSON Lines, which only names its fields record by
    record; for the other formats it is the header or the declared schema, so a
    column survives schema resolution even when the input holds no rows.
    """

    names: tuple[str, ...]
    records: Iterator[Record]


#: Tried in order, so that ``bool`` is not read as ``int`` and ``datetime`` not
#: as ``date``.
_RENDERERS = (
    (str, str),
    (bool, lambda value: "true" if value else "false"),
    (int, str),
    (float, repr),
    (datetime, render_timestamp),
    (date, date.isoformat),
    (bytes, bytes.decode),
)


def text_of(value) -> str | None:
    """Render an already typed value as the text the cast rules expect."""
    if value is None:
        return None
    for kind, renderer in _RENDERERS:
        if isinstance(value, kind):
            return renderer(value)
    return str(value)  # Decimal, and anything else arrow hands back


#: Range of a signed 64 bit integer, the "within range" of the number rule.
_INT_MIN, _INT_MAX = -(2**63), 2**63 - 1


def scalar_text(value) -> str | None:
    """Render one JSON scalar as text, applying the integral number rule.

    A JSON number written with a fractional part but holding an integer - and
    within the range of a 64 bit integer - reads as that integer (T31), inside
    a nested value as much as at the top level.
    """
    if isinstance(value, float) and value.is_integer() and _INT_MIN <= value <= _INT_MAX:
        return str(int(value))
    return text_of(value)


def cell_text(cell) -> str | None:
    """The text of a cell, whichever shape the reader handed it over in."""
    return scalar_text(cell.value) if isinstance(cell, JsonValue) else cell

"""What every reader yields, and how typed values reach the caster.

Readers hand the rest of the tool :class:`Record` objects: the field names the
record itself carries, the matching cell texts, and the position used in error
messages. Sources whose values arrive already typed (JSON Lines, parquet)
render them to text here, so that one set of cast rules serves every format.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterator, NamedTuple

from .casting import render_timestamp


class Record(NamedTuple):
    """One input row: its own field names, its cell texts, and where it came from."""

    names: tuple[str, ...]
    #: ``None`` marks a missing cell; the reader has already applied the
    #: nullness rule of its own dialect.
    values: list[str | None]
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

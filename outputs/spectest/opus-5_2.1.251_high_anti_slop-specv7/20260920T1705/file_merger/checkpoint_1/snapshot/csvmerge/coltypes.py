"""Column types: recognition, casting and deterministic output formatting.

A cell is always read as text.  ``candidate_types`` reports every type the text
could be cast to, ``cast`` performs the conversion and ``format_value`` renders
a cast value back into the output dialect.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import Callable, Iterable


class ColumnType(str, Enum):
    """The types a resolved schema column may have."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    DATE = "date"
    TIMESTAMP = "timestamp"


#: Order used to pick a column type from the set of types every one of its
#: values matches: the first match wins, so the most specific type is chosen.
#: ``date`` precedes ``timestamp`` because a column of plain ``YYYY-MM-DD``
#: values stays a date; as soon as one value carries a time component only
#: ``timestamp`` remains a candidate and the column is promoted to it, which is
#: the ``timestamp > date`` priority.
INFERENCE_ORDER = (
    ColumnType.DATE,
    ColumnType.TIMESTAMP,
    ColumnType.BOOL,
    ColumnType.INT,
    ColumnType.FLOAT,
    ColumnType.STRING,
)

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?\Z",
    re.IGNORECASE,
)
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})


class CastError(ValueError):
    """Raised when a cell cannot be represented as its column's type."""


def _parse_bool(text: str) -> bool:
    lowered = text.lower()
    if lowered in _TRUE_LITERALS:
        return True
    if lowered in _FALSE_LITERALS:
        return False
    raise ValueError(f"{text!r} is not a boolean")


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text!r} is not a finite number")
    return value


def _parse_date(text: str) -> date:
    if not _DATE_PATTERN.match(text):
        raise ValueError(f"{text!r} is not an ISO-8601 date")
    return date.fromisoformat(text)


def _parse_timestamp(text: str) -> datetime:
    """Parse an ISO-8601 timestamp (or plain date) and normalise it to UTC."""
    if not _TIMESTAMP_PATTERN.match(text) and not _DATE_PATTERN.match(text):
        raise ValueError(f"{text!r} is not an ISO-8601 timestamp")
    normalised = f"{text[:-1]}+00:00" if text[-1] in "Zz" else text
    moment = datetime.fromisoformat(normalised)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


_PARSERS: dict[ColumnType, Callable[[str], object]] = {
    ColumnType.STRING: str,
    ColumnType.INT: int,
    ColumnType.FLOAT: _parse_float,
    ColumnType.BOOL: _parse_bool,
    ColumnType.DATE: _parse_date,
    ColumnType.TIMESTAMP: _parse_timestamp,
}


def cast(text: str, column_type: ColumnType) -> object:
    """Cast raw cell text into ``column_type``, raising ``CastError`` on failure."""
    try:
        return _PARSERS[column_type](text)
    except ValueError as error:
        raise CastError(str(error)) from error


@lru_cache(maxsize=8192)
def candidate_types(text: str) -> frozenset[ColumnType]:
    """Every type ``text`` can be cast to; ``string`` is always among them."""
    matches = {ColumnType.STRING}
    for column_type in INFERENCE_ORDER:
        try:
            cast(text, column_type)
        except CastError:
            continue
        matches.add(column_type)
    return frozenset(matches)


def narrowest(candidates: Iterable[ColumnType]) -> ColumnType:
    """Pick the most specific type of a candidate set, per ``INFERENCE_ORDER``."""
    remaining = set(candidates)
    return next(column_type for column_type in INFERENCE_ORDER if column_type in remaining)


def format_value(value: object) -> str:
    """Render a cast value using the output dialect's textual conventions."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)

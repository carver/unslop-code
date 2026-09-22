"""The six spec types: parsing, canonical rendering and sort values.

Every type is described by one :class:`TypeHandler`, shared by schema casting
and by type inference so the two can never disagree about what parses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

#: Highest to lowest, per the spec's type priority.
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

_INT_RE = re.compile(r"[+-]?[0-9]+\Z")
_FLOAT_RE = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
#: A digit-separator-digit run is what makes a timestamp more than a date.
_TIME_PART_RE = re.compile(r"[0-9][T ][0-9]")

_BOOL_LITERALS = {"true": True, "false": False, "1": True, "0": False}


def _parse_int(text: str) -> int:
    """Digits with an optional sign; Python's own underscore forms are not ints here."""
    if not _INT_RE.match(text.strip()):
        raise ValueError(f"not an int: {text!r}")
    return int(text)


def _parse_float(text: str) -> float:
    """Decimal or exponent notation; `nan` and `inf` are text, not numbers."""
    if not _FLOAT_RE.match(text.strip()):
        raise ValueError(f"not a float: {text!r}")
    return float(text)


def _parse_bool(text: str) -> bool:
    """`true`/`false` in any case, plus `1`/`0`."""
    value = _BOOL_LITERALS.get(text.strip().lower())
    if value is None:
        raise ValueError(f"not a bool: {text!r}")
    return value


def _parse_date(text: str) -> date:
    """ISO-8601 calendar date, `YYYY-MM-DD` only."""
    stripped = text.strip()
    if not _DATE_RE.match(stripped):
        raise ValueError(f"not an ISO-8601 date: {text!r}")
    return date.fromisoformat(stripped)


def _parse_timestamp(text: str) -> datetime:
    """ISO-8601 datetime normalized to UTC; a zoneless source is read as UTC."""
    moment = datetime.fromisoformat(text.strip())
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def has_time_part(text: str) -> bool:
    """Whether `text` carries a clock time, distinguishing timestamps from dates."""
    return _TIME_PART_RE.search(text) is not None


@dataclass(frozen=True)
class TypeHandler:
    """How one type parses its text, renders its value, and orders its values."""

    parse: Callable[[str], Any]
    render: Callable[[Any], str]
    sort_value: Callable[[Any], Any]

    def accepts(self, text: str) -> bool:
        try:
            self.parse(text)
        except ValueError:
            return False
        return True


TYPES: dict[str, TypeHandler] = {
    "string": TypeHandler(str, str, str),
    "int": TypeHandler(_parse_int, str, int),
    "float": TypeHandler(_parse_float, str, float),
    "bool": TypeHandler(_parse_bool, lambda value: "true" if value else "false", int),
    "date": TypeHandler(_parse_date, date.isoformat, date.toordinal),
    "timestamp": TypeHandler(
        _parse_timestamp,
        lambda moment: moment.isoformat().replace("+00:00", "Z"),
        datetime.timestamp,
    ),
}


def cast(text: str, type_name: str) -> tuple[str, Any]:
    """Cast one cell, returning its output text and its comparable sort value."""
    handler = TYPES[type_name]
    value = handler.parse(text)
    return handler.render(value), handler.sort_value(value)


def matching_types(text: str) -> set[str]:
    """Every type that can parse `text`; always includes `string`."""
    return {name for name, handler in TYPES.items() if handler.accepts(text)}

"""The six column types: how their values parse, render and compare.

Each type is described once, in one `ColumnType`, so that casting, inference and
sort-key extraction all stay in agreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

# Highest priority first, as given by the spec's type priority list.
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIME_SEPARATORS = ("T", "t", " ")
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})


def _parse_bool(text: str) -> bool:
    """Accept the standard spellings of true/false plus the digits 1 and 0."""
    literal = text.strip().lower()
    if literal in _TRUE_LITERALS:
        return True
    if literal in _FALSE_LITERALS:
        return False
    raise ValueError(f"not a boolean: {text!r}")


def _parse_date(text: str) -> date:
    """Accept ISO-8601 calendar dates, and only in the YYYY-MM-DD spelling."""
    literal = text.strip()
    if not _DATE_PATTERN.match(literal):
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}")
    return date.fromisoformat(literal)


def _parse_timestamp(text: str) -> datetime:
    """Accept ISO-8601 date-times; a value without a time is a date, not a timestamp."""
    literal = text.strip()
    if not any(separator in literal for separator in _TIME_SEPARATORS):
        raise ValueError(f"not a timestamp: {text!r}")
    stamp = datetime.fromisoformat(literal)
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


def _render_timestamp(value: datetime) -> str:
    """UTC with a Z suffix, keeping fractional seconds when the source had them."""
    fraction = f".{value.microsecond:06d}" if value.microsecond else ""
    return f"{value:%Y-%m-%dT%H:%M:%S}{fraction}Z"


@dataclass(frozen=True)
class ColumnType:
    """Parsing, rendering and ordering behaviour of one declared type."""

    name: str
    parse: Callable[[str], object]
    render: Callable[[object], str]
    sort_value: Callable[[object], object]

    def accepts(self, text: str) -> bool:
        """Whether `text` is a value of this type, as used by schema inference."""
        try:
            self.parse(text)
        except ValueError:
            return False
        return True


TYPES = {
    definition.name: definition
    for definition in (
        ColumnType("string", str, str, str),
        ColumnType("int", int, str, int),
        ColumnType("float", float, repr, float),
        ColumnType("bool", _parse_bool, _render_bool, int),
        ColumnType("date", _parse_date, date.isoformat, date.toordinal),
        ColumnType("timestamp", _parse_timestamp, _render_timestamp, datetime.timestamp),
    )
}


def candidate_types(text: str) -> set[str]:
    """Every type that can parse `text`; always contains at least `string`."""
    return {name for name, definition in TYPES.items() if definition.accepts(text)}


def highest_priority(candidates: set[str]) -> str:
    """The most specific of `candidates` per the spec's priority list."""
    return next(name for name in TYPE_PRIORITY if name in candidates)

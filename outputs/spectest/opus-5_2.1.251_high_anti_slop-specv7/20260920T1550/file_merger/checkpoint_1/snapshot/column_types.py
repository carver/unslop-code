"""The value types a column can hold: parsing, rendering and ordering.

Every type knows three things:

``parse``
    Turn a CSV cell into a Python value, raising :class:`ValueError` when the
    text does not belong to the type.
``render``
    Turn that value back into the canonical text written to the output CSV.
``sort_value``
    Turn that value into something JSON serialisable whose natural ordering
    matches the type's ordering, so that keys survive a trip through a
    temporary spill file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Iterable

# Highest priority first: when a column's values parse as several types, the
# first entry that fits them all wins.
TYPE_PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")

_INT_RE = re.compile(r"[+-]?[0-9]+\Z")
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TIMESTAMP_RE = re.compile(
    r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})[T ]"
    r"(?P<clock>[0-9]{2}:[0-9]{2}(?::[0-9]{2})?)"
    r"(?:\.(?P<fraction>[0-9]+))?"
    r"(?P<zone>[Zz]|[+-][0-9]{2}:?[0-9]{2})?\Z"
)
_TRUE_LITERALS = frozenset({"true", "1"})
_FALSE_LITERALS = frozenset({"false", "0"})

# Fractional seconds are padded to this width in sort keys so that timestamps
# compare correctly as plain strings.
_SORT_FRACTION_WIDTH = 9


@dataclass(frozen=True)
class Timestamp:
    """An instant normalised to UTC, remembering how its fraction was written."""

    moment: datetime
    fraction: str


def _parse_int(text: str) -> int:
    stripped = text.strip()
    if not _INT_RE.match(stripped):
        raise ValueError(f"not an integer: {text!r}")
    return int(stripped)


def _parse_float(text: str) -> float:
    stripped = text.strip()
    if not _FLOAT_RE.match(stripped):
        raise ValueError(f"not a float: {text!r}")
    return float(stripped)


def _parse_bool(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in _TRUE_LITERALS:
        return True
    if lowered in _FALSE_LITERALS:
        return False
    raise ValueError(f"not a boolean: {text!r}")


def _parse_date(text: str) -> date:
    stripped = text.strip()
    if not _DATE_RE.match(stripped):
        raise ValueError(f"not an ISO-8601 date: {text!r}")
    return date.fromisoformat(stripped)


def _parse_timestamp(text: str) -> Timestamp:
    match = _TIMESTAMP_RE.match(text.strip())
    if match is None:
        raise ValueError(f"not an ISO-8601 timestamp: {text!r}")
    clock = match["clock"] if len(match["clock"]) == 8 else f"{match['clock']}:00"
    # A missing zone is read as UTC, as the spec requires.
    zone = (match["zone"] or "Z").upper()
    moment = datetime.fromisoformat(f"{match['day']}T{clock}{zone}")
    return Timestamp(moment.astimezone(timezone.utc), match["fraction"] or "")


def _identity(value: object) -> object:
    """Values that are already comparable and JSON friendly sort as themselves."""
    return value


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


def _render_timestamp(value: Timestamp) -> str:
    fraction = f".{value.fraction}" if value.fraction else ""
    return f"{value.moment:%Y-%m-%dT%H:%M:%S}{fraction}Z"


def _timestamp_sort_value(value: Timestamp) -> str:
    return f"{value.moment:%Y-%m-%dT%H:%M:%S}.{value.fraction:0<{_SORT_FRACTION_WIDTH}}"


@dataclass(frozen=True)
class ColumnType:
    """One supported column type and the three operations defined on it."""

    name: str
    parse: Callable[[str], object]
    render: Callable[[object], str]
    sort_value: Callable[[object], object]


TYPES: dict[str, ColumnType] = {
    column_type.name: column_type
    for column_type in (
        ColumnType("string", str, str, _identity),
        ColumnType("int", _parse_int, str, _identity),
        ColumnType("float", _parse_float, str, _identity),
        ColumnType("bool", _parse_bool, _render_bool, _identity),
        ColumnType("date", _parse_date, date.isoformat, date.isoformat),
        ColumnType("timestamp", _parse_timestamp, _render_timestamp, _timestamp_sort_value),
    )
}


def matching_types(text: str, among: Iterable[str]) -> set[str]:
    """Return the names in ``among`` whose type can parse ``text``.

    Inference narrows a column's candidates value by value, so it only ever
    asks about the types that are still in the running.
    """
    matches = set()
    for name in among:
        try:
            TYPES[name].parse(text)
        except ValueError:
            continue
        matches.add(name)
    return matches


def best_type(candidates: set[str]) -> str:
    """Pick the highest priority type among ``candidates``."""
    return next(name for name in TYPE_PRIORITY if name in candidates)

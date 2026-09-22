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
    """How one type parses its text, renders its value, and orders its values.

    `json_value` is the value's form inside a nested column's JSON, which is a
    native JSON number or boolean where the type has one, and text otherwise.
    """

    parse: Callable[[str], Any]
    render: Callable[[Any], str]
    sort_value: Callable[[Any], Any]
    json_value: Callable[[Any], Any] = str

    def accepts(self, text: str) -> bool:
        try:
            self.parse(text)
        except ValueError:
            return False
        return True


def _render_timestamp(moment: datetime) -> str:
    """ISO-8601 in UTC, with the `Z` suffix the spec asks for."""
    return moment.isoformat().replace("+00:00", "Z")


TYPES: dict[str, TypeHandler] = {
    "string": TypeHandler(str, str, str, str),
    "int": TypeHandler(_parse_int, str, int, int),
    "float": TypeHandler(_parse_float, str, float, float),
    "bool": TypeHandler(_parse_bool, lambda value: "true" if value else "false", int, bool),
    "date": TypeHandler(_parse_date, date.isoformat, date.toordinal, date.isoformat),
    "timestamp": TypeHandler(
        _parse_timestamp, _render_timestamp, datetime.timestamp, _render_timestamp
    ),
}


def cast(text: str, type_name: str) -> tuple[str, Any]:
    """Cast one cell, returning its output text and its comparable sort value."""
    handler = TYPES[type_name]
    value = handler.parse(text)
    return handler.render(value), handler.sort_value(value)


def cast_leaf(text: str, type_name: str) -> Any:
    """Cast one primitive value to the form it takes inside a nested column."""
    handler = TYPES[type_name]
    return handler.json_value(handler.parse(text))


def matching_types(text: str) -> set[str]:
    """Every type that can parse `text`; always includes `string`."""
    return {name for name, handler in TYPES.items() if handler.accepts(text)}


#: How a native value from a typed source spells itself as text. Keyed by exact
#: type so that `bool` never falls through to the `int` entry.
_TEXT_BY_TYPE = {
    str: lambda value: value,
    bytes: lambda value: value.decode("utf-8"),
    bool: lambda value: "true" if value else "false",
    datetime: TYPES["timestamp"].render,
    date: date.isoformat,
}

#: The schema type a native value reports itself as, for inference.
_TYPE_BY_NATIVE = {
    str: "string",
    bytes: "string",
    bool: "bool",
    int: "int",
    float: "float",
    datetime: "timestamp",
    date: "date",
}

#: Pairs of types with a common type simpler than `string`.
_WIDENINGS = {
    frozenset({"int", "float"}): "float",
    frozenset({"date", "timestamp"}): "timestamp",
}


def to_text(value: Any) -> str:
    """The canonical text of a value from a typed source, ready to be cast."""
    return _TEXT_BY_TYPE.get(type(value), str)(value)


def native_type(value: Any) -> str:
    """The schema type a typed source's value declares itself to be."""
    return _TYPE_BY_NATIVE.get(type(value), "string")


def widen(left: str, right: str) -> str:
    """The simplest type that can hold every value of both types."""
    if left == right:
        return left
    return _WIDENINGS.get(frozenset({left, right}), "string")

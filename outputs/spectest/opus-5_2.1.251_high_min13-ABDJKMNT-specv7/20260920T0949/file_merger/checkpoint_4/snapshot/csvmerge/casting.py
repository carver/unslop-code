"""The six schema types and the operations the rest of the tool needs from them.

Each type is a :class:`TypeSpec` bundling four operations:

``parse``
    text -> Python value, raising :class:`UnfitValue` when the text does not fit.
``render``
    Python value -> the text written to the output CSV.
``sort_value``
    Python value -> a JSON encodable value that orders like the original, so
    sort keys survive a round trip through a spill file.
``recognize``
    text -> bool, the predicate schema inference uses. It is stricter than
    ``parse`` for timestamps: a bare ``YYYY-MM-DD`` casts to midnight UTC but is
    recognised as a ``date`` rather than as a ``timestamp``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

# Deliberately stricter than int()/float(), which also accept underscore
# separators, "nan" and "inf".
_INT_RE = re.compile(r"[+-]?[0-9]+\Z")
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}")

_TRUE_TEXT = frozenset({"true", "1"})
_FALSE_TEXT = frozenset({"false", "0"})

#: Highest priority first, as given by the spec's type priority list.
PRIORITY = ("timestamp", "date", "bool", "int", "float", "string")


class CastError(ValueError):
    """A value that does not fit the type its field is declared with.

    The message is the body of the spec's ``ERR 4`` line; the reader adds the
    file and line it came from.
    """

    def __init__(self, value: str, type_label: str, path: str):
        super().__init__(f'cannot cast "{value}" to {type_label} in field "{path}"')


class UnfitValue(ValueError):
    """Raised by a parser; the caster turns it into a :class:`CastError`."""


class RawText(str):
    """Cell text preserved verbatim by ``--on-type-error keep-string``."""


def _parse_int(text: str) -> int:
    stripped = text.strip()
    if not _INT_RE.match(stripped):
        raise UnfitValue
    return int(stripped)


def _parse_float(text: str) -> float:
    stripped = text.strip()
    if not _FLOAT_RE.match(stripped):
        raise UnfitValue
    return float(stripped)


def _parse_bool(text: str) -> bool:
    stripped = text.strip().lower()
    if stripped in _TRUE_TEXT:
        return True
    if stripped in _FALSE_TEXT:
        return False
    raise UnfitValue


def _parse_date(text: str) -> date:
    stripped = text.strip()
    if not _DATE_RE.match(stripped):
        raise UnfitValue
    try:
        return date.fromisoformat(stripped)
    except ValueError:
        raise UnfitValue from None


def _parse_timestamp(text: str) -> datetime:
    """Parse an ISO-8601 instant and normalise it to UTC.

    A value without a zone is taken as UTC; a bare date becomes midnight UTC.
    """
    stripped = text.strip()
    if _DATE_RE.match(stripped):
        return datetime.fromisoformat(stripped).replace(tzinfo=timezone.utc)
    if not _TIMESTAMP_RE.match(stripped):
        raise UnfitValue
    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        raise UnfitValue from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def render_timestamp(value: datetime) -> str:
    """Emit UTC with a ``Z`` suffix, keeping fractional seconds when present."""
    return value.isoformat().replace("+00:00", "Z")


def _recognizer(parse: Callable[[str], object]) -> Callable[[str], bool]:
    def recognize(text: str) -> bool:
        try:
            parse(text)
        except UnfitValue:
            return False
        return True

    return recognize


def _recognize_timestamp(text: str) -> bool:
    """Inference only calls a value a timestamp when it carries a time of day."""
    return _TIMESTAMP_RE.match(text.strip()) is not None and _recognizer(_parse_timestamp)(text)


@dataclass(frozen=True)
class TypeSpec:
    """One schema type: how to parse, render, order and recognise its values."""

    name: str
    parse: Callable[[str], object]
    render: Callable[[object], str]
    sort_value: Callable[[object], object]
    recognize: Callable[[str], bool]


def _spec(name, parse, render, sort_value, recognize=None) -> TypeSpec:
    return TypeSpec(name, parse, render, sort_value, recognize or _recognizer(parse))


TYPES = {
    spec.name: spec
    for spec in (
        _spec("string", str, str, str),
        _spec("int", _parse_int, str, lambda value: value),
        _spec("float", _parse_float, repr, lambda value: value),
        _spec("bool", _parse_bool, lambda value: "true" if value else "false", int),
        _spec("date", _parse_date, date.isoformat, date.toordinal),
        _spec("timestamp", _parse_timestamp, render_timestamp, datetime.timestamp, _recognize_timestamp),
    )
}


def cast(text: str, spec: TypeSpec, on_type_error: str, path: str):
    """Cast one non-null cell, applying the ``--on-type-error`` policy.

    ``path`` is the field the text sat in - a column name, or a dotted path
    into a nested value - and names the field in the error message.
    """
    try:
        return spec.parse(text)
    except UnfitValue:
        if on_type_error == "fail":
            raise CastError(text, spec.name, path) from None
        return RawText(text) if on_type_error == "keep-string" else None


def render_value(value, spec: TypeSpec) -> str:
    """Render one non-null cast value; text kept by ``keep-string`` passes through."""
    return str(value) if isinstance(value, RawText) else spec.render(value)


def render(value, spec: TypeSpec, null_literal: str) -> str:
    """Render a cast value as output text; nulls become the null literal."""
    return null_literal if value is None else render_value(value, spec)


def sort_part(value, spec: TypeSpec) -> list:
    """Project a value onto ``[non_null, rank, comparable]``.

    Nulls come first because they carry a lower leading element, and text kept
    by ``keep-string`` is ranked after properly typed values so that the
    comparable elements of a column are never of mixed Python types.
    """
    if value is None:
        return [0, 0, 0]
    if isinstance(value, RawText):
        return [1, 1, str(value)]
    return [1, 0, spec.sort_value(value)]


#: The types a declared type can widen into, for sources that carry their own
#: schema: a parquet ``int64`` column also fits ``float`` and ``string``.
WIDENING = {
    "string": frozenset({"string"}),
    "int": frozenset({"int", "float", "string"}),
    "float": frozenset({"float", "string"}),
    "bool": frozenset({"bool", "string"}),
    "date": frozenset({"date", "string"}),
    "timestamp": frozenset({"timestamp", "string"}),
}


def best_type(candidates) -> str:
    """Pick the highest priority type among ``candidates``."""
    for name in PRIORITY:
        if name in candidates:
            return name
    return "string"

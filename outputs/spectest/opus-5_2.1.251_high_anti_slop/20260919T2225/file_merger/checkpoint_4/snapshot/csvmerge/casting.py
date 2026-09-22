"""Casting a single value into a primitive type, and ordering the result."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .datatypes import DataType, describe
from .errors import CastError
from .types import FORMATTERS, SORT_ENCODERS, ColumnType, as_text, cast_value


class TypeErrorPolicy(str, Enum):
    """What to do with a value that does not parse as its declared type."""

    COERCE_NULL = "coerce-null"
    FAIL = "fail"
    KEEP_STRING = "keep-string"


@dataclass(frozen=True)
class CastContext:
    """What a cast needs beyond the value itself: the policy, and where it came from.

    ``origin`` is the ``file=... line=...`` tail of a cast error message.
    ``parse_text`` marks a source whose values arrive as text, so that a nested
    value has to be read out of a JSON literal first.
    """

    policy: TypeErrorPolicy
    origin: str
    parse_text: bool


@dataclass(frozen=True)
class Cell:
    """A cast value: parsed, null, or text kept after a failed cast.

    ``kind`` is the primitive type the value was parsed as, which decides how it
    is rendered and how it sorts; it stays ``None`` for a null, which needs no
    type to be written or compared.
    """

    value: Any
    kind: ColumnType | None = None
    kept_raw: bool = False


NULL_CELL = Cell(None)

#: Sort tiers. Nulls always compare lowest; text kept by ``keep-string`` cannot
#: be compared against parsed values, so it is ordered after them.
_NULL_TIER = 0
_VALUE_TIER = 1
_RAW_TIER = 2


def cast_cell(value: Any, kind: ColumnType, path: str, context: CastContext) -> Cell:
    """Cast one input value into ``kind``, applying the policy on failure.

    Readers hand over ``None`` for anything missing — an empty CSV cell, a JSON
    ``null``, an absent field — so every source spells a null the same way here.
    """
    if value is None:
        return NULL_CELL
    try:
        return Cell(cast_value(value, kind), kind)
    except ValueError:
        return on_failure(value, kind, path, context)


def on_failure(value: Any, data_type: DataType, path: str, context: CastContext) -> Cell:
    """Apply ``--on-type-error`` to a value that does not fit ``data_type``."""
    text = as_text(value)
    if context.policy is TypeErrorPolicy.FAIL:
        raise CastError(
            f'cannot cast "{text}" to {describe(data_type)} in field "{path}" ({context.origin})'
        )
    if context.policy is TypeErrorPolicy.KEEP_STRING:
        return Cell(text, ColumnType.STRING, kept_raw=True)
    return NULL_CELL


def format_cell(cell: Cell, null_literal: str) -> str:
    """Render a cell as output CSV text."""
    if cell.value is None:
        return null_literal
    return FORMATTERS[cell.kind](cell.value)


def key_fragment(cell: Cell) -> list:
    """Encode a cell as a JSON-safe, lexicographically comparable sort fragment."""
    if cell.value is None:
        return [_NULL_TIER]
    if cell.kept_raw:
        return [_RAW_TIER, cell.value]
    return [_VALUE_TIER, SORT_ENCODERS[cell.kind](cell.value)]

"""Turning raw input cells into output text and sort-key fragments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .dialect import CsvDialect
from .errors import MergeError
from .schema import Column
from .types import FORMATTERS, PARSERS, SORT_ENCODERS


class TypeErrorPolicy(str, Enum):
    """What to do with a cell that does not parse as its column's type."""

    COERCE_NULL = "coerce-null"
    FAIL = "fail"
    KEEP_STRING = "keep-string"


@dataclass(frozen=True)
class Cell:
    """A cast cell: a parsed value, a null, or raw text kept after a failed cast."""

    value: Any
    kept_raw: bool = False


NULL_CELL = Cell(None)

#: Sort tiers. Nulls always compare lowest; text kept by ``keep-string`` cannot
#: be compared against parsed values, so it is ordered after them.
_NULL_TIER = 0
_VALUE_TIER = 1
_RAW_TIER = 2


def cast_cell(text: str | None, column: Column, dialect: CsvDialect, policy: TypeErrorPolicy) -> Cell:
    """Cast one input cell into ``column``'s type, applying ``policy`` on failure."""
    if text is None or dialect.is_null(text):
        return NULL_CELL
    try:
        return Cell(PARSERS[column.type](text))
    except ValueError:
        return _on_failure(text, column, policy)


def format_cell(cell: Cell, column: Column, null_literal: str) -> str:
    """Render a cell as output CSV text."""
    if cell.value is None:
        return null_literal
    if cell.kept_raw:
        return cell.value
    return FORMATTERS[column.type](cell.value)


def key_fragment(cell: Cell, column: Column) -> list:
    """Encode a cell as a JSON-safe, lexicographically comparable sort fragment."""
    if cell.value is None:
        return [_NULL_TIER]
    if cell.kept_raw:
        return [_RAW_TIER, cell.value]
    return [_VALUE_TIER, SORT_ENCODERS[column.type](cell.value)]


def _on_failure(text: str, column: Column, policy: TypeErrorPolicy) -> Cell:
    if policy is TypeErrorPolicy.FAIL:
        raise MergeError(f"column {column.name!r}: cannot cast {text!r} to {column.type.value}")
    if policy is TypeErrorPolicy.KEEP_STRING:
        return Cell(text, kept_raw=True)
    return NULL_CELL

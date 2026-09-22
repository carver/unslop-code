"""Turning input rows into cast output rows paired with their sort keys."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from .casting import cast
from .csvio import open_table
from .errors import MergeError
from .schema import Column, Schema

#: Rank prefixes that order nulls before every value, and text kept by
#: `--on-type-error keep-string` after every well-typed value.
NULL_RANK, VALUE_RANK, RAW_RANK = 0, 1, 2

#: Placeholder paired with NULL_RANK so that key parts stay comparable.
_NULL_SORT_VALUE = ""


@dataclass(frozen=True)
class CastPolicy:
    """How cells become output text: what counts as null, and what a bad cast does."""

    on_error: str
    null_literal: str

    def is_null(self, text: str | None) -> bool:
        """A missing cell, an empty cell, or one spelled as the null literal."""
        return text is None or text == "" or text == self.null_literal


def iter_records(
    paths: Sequence[str],
    dialect: dict,
    schema: Schema,
    key_names: Sequence[str],
    policy: CastPolicy,
) -> Iterator[tuple[list, list[str]]]:
    """Yield `(sort key, output row)` for every data row, in input appearance order."""
    key_positions = [schema.names.index(name) for name in key_names]
    for path in paths:
        with open_table(path, dialect) as (header, rows):
            for line_number, row in enumerate(rows, start=2):
                if not row:  # a blank line is not a record
                    continue
                values = dict(zip(header, row))
                location = f"{path}:{line_number}"
                cells = [
                    _cast_cell(values.get(column.name), column, policy, location)
                    for column in schema.columns
                ]
                yield [cells[at][1] for at in key_positions], [text for text, _ in cells]


def _cast_cell(
    text: str | None, column: Column, policy: CastPolicy, where: str
) -> tuple[str, list[Any]]:
    """The output text and sort key part for one cell."""
    if policy.is_null(text):
        return policy.null_literal, [NULL_RANK, _NULL_SORT_VALUE]
    try:
        rendered, sort_value = cast(text, column.type)
    except ValueError:
        return _handle_cast_failure(text, column, policy, where)
    return rendered, [VALUE_RANK, sort_value]


def _handle_cast_failure(
    text: str, column: Column, policy: CastPolicy, where: str
) -> tuple[str, list[Any]]:
    """Apply `--on-type-error` to a cell that would not cast."""
    if policy.on_error == "fail":
        raise MergeError(
            f"{where}: cannot cast {text!r} to {column.type} in column {column.name!r}"
        )
    if policy.on_error == "keep-string":
        return text, [RAW_RANK, text]
    return policy.null_literal, [NULL_RANK, _NULL_SORT_VALUE]

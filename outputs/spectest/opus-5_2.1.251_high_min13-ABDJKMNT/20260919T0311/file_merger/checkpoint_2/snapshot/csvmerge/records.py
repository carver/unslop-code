"""Turning input rows into cast output rows paired with their sort keys."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence

from .casting import cast, to_text
from .cli import Options
from .errors import EXIT_CAST, MergeError
from .formats import InputFile
from .schema import Column, Schema
from .sources import open_source

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
    inputs: Sequence[InputFile],
    options: Options,
    schema: Schema,
    key_names: Sequence[str],
    policy: CastPolicy,
) -> Iterator[tuple[list, list[str]]]:
    """Yield `(sort key, output row)` for every data row, in input appearance order."""
    key_positions = [schema.names.index(name) for name in key_names]
    for source in inputs:
        with open_source(source, options) as opened:
            for number, row in enumerate(opened.rows, start=opened.first_row):
                location = f"{source.path}:{number}"
                cells = [
                    _cast_cell(row.get(column.name), column, opened.typed, policy, location)
                    for column in schema.columns
                ]
                yield [cells[at][1] for at in key_positions], [text for text, _ in cells]


def _cast_cell(
    value: Any, column: Column, typed: bool, policy: CastPolicy, where: str
) -> tuple[str, list[Any]]:
    """The output text and sort key part for one cell."""
    if value is None or (not typed and policy.is_null(value)):
        return policy.null_literal, [NULL_RANK, _NULL_SORT_VALUE]
    text = to_text(value)
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
            f"{where}: cannot cast {text!r} to {column.type} in column {column.name!r}",
            EXIT_CAST,
        )
    if policy.on_error == "keep-string":
        return text, [RAW_RANK, text]
    return policy.null_literal, [NULL_RANK, _NULL_SORT_VALUE]

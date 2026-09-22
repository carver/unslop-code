"""Streaming input rows into schema-aligned, sortable records."""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Sequence

from .casting import TypeErrorPolicy, cast_cell, format_cell, key_fragment
from .csvio import open_csv
from .dialect import CsvDialect
from .schema import Schema
from .sorting import Record


def iter_records(
    paths: Sequence[str],
    schema: Schema,
    dialect: CsvDialect,
    policy: TypeErrorPolicy,
    key_indexes: Sequence[int],
) -> Iterator[Record]:
    """Yield one record per input row, in input order.

    Each row is projected onto the resolved schema — columns the file does not
    have become nulls, columns the schema does not have are dropped — then cast
    and rendered once, so the sorter only ever moves finished output text.
    """
    sequence = itertools.count()
    for path in paths:
        with open_csv(path, dialect) as (header, rows):
            for row in rows:
                texts = dict(zip(header, row))
                cells = [cast_cell(texts.get(column.name), column, dialect, policy) for column in schema.columns]
                yield Record(
                    keys=[key_fragment(cells[index], schema.columns[index]) for index in key_indexes],
                    seq=next(sequence),
                    row=[
                        format_cell(cell, column, dialect.null_literal)
                        for cell, column in zip(cells, schema.columns)
                    ],
                )

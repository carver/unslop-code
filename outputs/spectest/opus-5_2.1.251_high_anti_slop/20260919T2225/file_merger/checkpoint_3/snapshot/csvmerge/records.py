"""Streaming input rows into schema-aligned, sortable records."""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Sequence

from .casting import TypeErrorPolicy, cast_cell, format_cell, key_fragment
from .partitioning import PartitionScheme
from .schema import Schema
from .sorting import Record
from .sources import InputSpec, ReadOptions, read_rows


def iter_records(
    specs: Sequence[InputSpec],
    schema: Schema,
    options: ReadOptions,
    policy: TypeErrorPolicy,
    key_indexes: Sequence[int],
    scheme: PartitionScheme,
) -> Iterator[Record]:
    """Yield one record per input row, in input order.

    Each row is projected onto the resolved schema — columns the file does not
    have become nulls, columns the schema does not have are dropped — then cast
    and rendered once, so the sorter only ever moves finished output text. The
    partition segments are derived from the same cast cells, so a value is
    spelled in its directory name exactly as the schema's type renders it.
    """
    sequence = itertools.count()
    null_literal = options.dialect.null_literal
    for spec in specs:
        for values in read_rows(spec, options):
            cells = [cast_cell(values.get(column.name), column, policy) for column in schema.columns]
            yield Record(
                keys=[key_fragment(cells[index], schema.columns[index]) for index in key_indexes],
                seq=next(sequence),
                row=[format_cell(cell, column, null_literal) for cell, column in zip(cells, schema.columns)],
                partition=scheme.segments(cells),
            )

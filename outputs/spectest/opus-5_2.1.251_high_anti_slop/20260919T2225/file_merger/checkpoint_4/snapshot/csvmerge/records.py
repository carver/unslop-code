"""Streaming input rows into schema-aligned, sortable records."""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Sequence

from .casting import CastContext, TypeErrorPolicy, key_fragment
from .nested import cast_column, format_column
from .partitioning import PartitionScheme
from .paths import ResolvedPath
from .schema import Schema
from .sorting import Record
from .sources import InputSpec, ReadOptions, read_rows


def iter_records(
    specs: Sequence[InputSpec],
    schema: Schema,
    options: ReadOptions,
    policy: TypeErrorPolicy,
    keys: Sequence[ResolvedPath],
    scheme: PartitionScheme,
    allow_nested: bool,
) -> Iterator[Record]:
    """Yield one record per input row, in input order.

    Each row is projected onto the resolved schema — columns the file does not
    have become nulls, columns the schema does not have are dropped — then cast
    and rendered once, so the sorter only ever moves finished output text. The
    sort keys and the partition segments are read out of the same cast columns,
    so a value is spelled in its directory name exactly as its type renders it.
    """
    sequence = itertools.count()
    null_literal = options.dialect.null_literal
    for spec in specs:
        for row in read_rows(spec, options, allow_nested):
            context = CastContext(policy, f"file={spec.path} line={row.line}", spec.yields_text)
            columns = [
                cast_column(row.values.get(column.name), column.type, column.name, context)
                for column in schema.columns
            ]
            yield Record(
                keys=[key_fragment(key.extract(columns)) for key in keys],
                seq=next(sequence),
                row=[format_column(column, null_literal) for column in columns],
                partition=scheme.segments(columns),
            )

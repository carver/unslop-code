"""Turning input rows into cast output rows paired with their sort keys."""
from __future__ import annotations

from typing import Iterator, Sequence

from .cli import Options
from .formats import InputFile
from .partitioning import hive_path
from .paths import FieldPath
from .schema import Schema
from .sources import open_source
from .values import CastPolicy, ValueCaster


def iter_records(
    inputs: Sequence[InputFile],
    options: Options,
    schema: Schema,
    keys: Sequence[FieldPath],
    policy: CastPolicy,
    partitions: Sequence[FieldPath] = (),
) -> Iterator[tuple[list, list[str]]]:
    """Yield `(sort key, output row)` for every data row, in input appearance order.

    The sort key leads with the row's partition directory, so sorting groups
    each partition together and orders the rows inside it by `--key`.
    """
    partition_names = [path.text for path in partitions]
    for source in inputs:
        with open_source(source, options, nested_allowed=bool(options.schema)) as opened:
            for number, row in enumerate(opened.rows, start=opened.first_row):
                caster = ValueCaster(policy, opened.typed,
                                     f"file={source.path} line={number}")
                cells = [caster.cell(row.get(column.name), column)
                         for column in schema.columns]
                directory = hive_path(
                    partition_names, [path.fragment(cells)[0] for path in partitions]
                )
                yield ([directory, *(path.fragment(cells)[1] for path in keys)],
                       [cell.text for cell in cells])

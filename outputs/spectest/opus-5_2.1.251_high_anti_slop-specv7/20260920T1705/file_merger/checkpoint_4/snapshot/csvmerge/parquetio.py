"""Parquet input, read one row group batch at a time.

The file's own schema supplies the column types, so no value scan is needed to
infer them.  A nested column is reported as the flexible ``json`` type: its
values are handed on as dicts and lists for the declared schema to cast, and
without one, schema inference rejects the file.  Rows are streamed in batches
sized from the advisory ``--parquet-row-group-bytes`` budget, which keeps the
reader's footprint independent of the file's size.
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from typing import Iterator

import pyarrow.parquet as pq
from pyarrow import types as arrow_types

from .coltypes import ColumnType
from .datatypes import JSON, DataType
from .formats import InputRow, Source, open_binary

#: Arrow type predicates in the order they are tried; anything unrecognised
#: (times, durations, opaque binary) is carried through as text.
_ARROW_TYPES = (
    (arrow_types.is_boolean, ColumnType.BOOL),
    (arrow_types.is_integer, ColumnType.INT),
    (arrow_types.is_floating, ColumnType.FLOAT),
    (arrow_types.is_decimal, ColumnType.FLOAT),
    (arrow_types.is_date, ColumnType.DATE),
    (arrow_types.is_timestamp, ColumnType.TIMESTAMP),
)


def read_types(source: Source) -> dict[str, DataType]:
    """Map the file's declared columns onto the tool's column types."""
    with _open(source) as parquet:
        return {field.name: _column_type(field.type) for field in parquet.schema_arrow}


def read_rows(source: Source) -> Iterator[InputRow]:
    """Yield every row as a mapping of column name to typed value."""
    with _open(source) as parquet:
        positions = itertools.count(1)
        for batch in parquet.iter_batches(batch_size=_batch_rows(parquet, source.row_group_bytes)):
            for values in batch.to_pylist(maps_as_pydicts="lossy"):
                yield InputRow(next(positions), values)


@contextmanager
def _open(source: Source) -> Iterator[pq.ParquetFile]:
    with open_binary(source.path, source.compression) as handle, pq.ParquetFile(handle) as parquet:
        yield parquet


def _column_type(arrow_type: object) -> DataType:
    """Name a column's type; nesting is only ever described by ``--schema``."""
    if arrow_types.is_nested(arrow_type):
        return JSON
    return next(
        (column_type for matches, column_type in _ARROW_TYPES if matches(arrow_type)),
        ColumnType.STRING,
    )


def _batch_rows(parquet: pq.ParquetFile, row_group_bytes: int) -> int:
    """Rows per batch that keep a batch near the advisory byte budget."""
    metadata = parquet.metadata
    if not metadata.num_rows:
        return 1
    stored = sum(
        metadata.row_group(index).total_byte_size for index in range(metadata.num_row_groups)
    )
    return max(row_group_bytes * metadata.num_rows // stored, 1)

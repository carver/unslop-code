"""Parquet input, read one row group batch at a time.

The file's own schema supplies the column types, so no value scan is needed to
infer them.  Rows are streamed in batches sized from the advisory
``--parquet-row-group-bytes`` budget, which keeps the reader's footprint
independent of the file's size.
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from typing import Iterator

import pyarrow.parquet as pq
from pyarrow import Schema as ArrowSchema, types as arrow_types

from .coltypes import ColumnType
from .errors import NestedDataError
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


def read_types(source: Source) -> dict[str, ColumnType]:
    """Map the file's declared columns onto the tool's column types."""
    with _open(source) as parquet:
        schema = parquet.schema_arrow
        _require_flat(source.path, schema)
        return {field.name: _column_type(field.type) for field in schema}


def read_rows(source: Source) -> Iterator[InputRow]:
    """Yield every row as a mapping of column name to typed value."""
    with _open(source) as parquet:
        _require_flat(source.path, parquet.schema_arrow)
        positions = itertools.count(1)
        for batch in parquet.iter_batches(batch_size=_batch_rows(parquet, source.row_group_bytes)):
            for values in batch.to_pylist():
                yield InputRow(next(positions), values)


@contextmanager
def _open(source: Source) -> Iterator[pq.ParquetFile]:
    with open_binary(source.path, source.compression) as handle, pq.ParquetFile(handle) as parquet:
        yield parquet


def _require_flat(path: str, schema: ArrowSchema) -> None:
    nested = sorted(field.name for field in schema if arrow_types.is_nested(field.type))
    if nested:
        raise NestedDataError(
            f"{path}: column(s) {', '.join(nested)} have nested types; "
            "only flat Parquet schemas are supported"
        )


def _column_type(arrow_type: object) -> ColumnType:
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

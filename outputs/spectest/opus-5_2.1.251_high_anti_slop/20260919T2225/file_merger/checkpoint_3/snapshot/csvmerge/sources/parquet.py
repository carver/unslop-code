"""Reading Parquet row group by row group, never the whole file at once."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pyarrow
import pyarrow.parquet as parquet
import pyarrow.types as arrow_types

from ..errors import MalformedInputError, NestedDataError
from ..types import ColumnType
from .files import InputSpec, ReadOptions, open_binary
from .scanning import Candidates

#: Arrow types are already precise, so a Parquet column's candidates come from
#: its schema and no data has to be read to infer one.
_ARROW_CANDIDATES = (
    (arrow_types.is_boolean, {ColumnType.BOOL, ColumnType.STRING}),
    (arrow_types.is_integer, {ColumnType.INT, ColumnType.FLOAT, ColumnType.STRING}),
    (arrow_types.is_floating, {ColumnType.FLOAT, ColumnType.STRING}),
    (arrow_types.is_decimal, {ColumnType.FLOAT, ColumnType.STRING}),
    (arrow_types.is_timestamp, {ColumnType.TIMESTAMP, ColumnType.STRING}),
    (arrow_types.is_date, {ColumnType.DATE, ColumnType.STRING}),
)

#: Ceiling on the rows materialised at once, whatever the byte budget works out to.
_MAX_BATCH_ROWS = 20000


def read_rows(spec: InputSpec, options: ReadOptions) -> Iterator[dict[str, Any]]:
    """Yield one dictionary per row, materialising a batch of rows at a time."""
    with _open(spec) as source:
        _flat_fields(spec, source)
        for batch in source.iter_batches(batch_size=_batch_size(source, options.parquet_row_group_bytes)):
            yield from batch.to_pylist()


def scan_types(spec: InputSpec, _options: ReadOptions, _ignore_nulls: bool) -> Candidates:
    """Report each column's candidate types straight from the Parquet schema."""
    with _open(spec) as source:
        return {field.name: _candidates(field.type) for field in _flat_fields(spec, source)}


@contextmanager
def _open(spec: InputSpec) -> Iterator[parquet.ParquetFile]:
    """Open the file, reporting an input that is not Parquet after all as malformed."""
    with open_binary(spec) as stream:
        try:
            source = parquet.ParquetFile(stream)
        except pyarrow.ArrowInvalid as error:
            raise MalformedInputError(f"{spec.path}: not a readable Parquet file") from error
        with source:
            yield source


def _flat_fields(spec: InputSpec, source: parquet.ParquetFile):
    """Return the file's fields, rejecting list, map and struct columns."""
    schema = source.schema_arrow
    nested = [field.name for field in schema if arrow_types.is_nested(field.type)]
    if nested:
        raise NestedDataError(f"{spec.path}: nested column(s) {', '.join(nested)}")
    return schema


def _candidates(arrow_type) -> set[ColumnType]:
    return next((types for matches, types in _ARROW_CANDIDATES if matches(arrow_type)), {ColumnType.STRING})


def _batch_size(source: parquet.ParquetFile, batch_bytes: int) -> int:
    """Turn the advisory byte budget into a row count, using the file's own row size.

    The cap matters because the budget is measured in Parquet's encoded bytes:
    a heavily compressed file would otherwise ask for a batch whose Python rows
    are an order of magnitude larger than the budget.
    """
    metadata = source.metadata
    if not metadata.num_rows:
        return 1
    group = metadata.row_group(0)
    rows = int(batch_bytes / max(group.total_byte_size / group.num_rows, 1))
    return max(1, min(rows, _MAX_BATCH_ROWS))

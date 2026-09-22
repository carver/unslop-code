"""Reading Parquet row group by row group, never the whole file at once."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from contextlib import contextmanager

import pyarrow
import pyarrow.parquet as parquet
import pyarrow.types as arrow_types

from ..errors import MalformedInputError, NestedDataError
from ..types import ColumnType
from .files import InputSpec, ReadOptions, open_binary
from .rows import SourceRow
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


def read_rows(spec: InputSpec, options: ReadOptions, allow_nested: bool) -> Iterator[SourceRow]:
    """Yield one row per record, materialising a batch of rows at a time.

    Structs arrive as dictionaries, lists as lists and maps as key/value pairs,
    all of which the nested casts understand; without a ``--schema`` declaring
    those columns they are rejected instead.
    """
    with _open(spec) as source:
        if not allow_nested:
            _reject_nested(spec, source.schema_arrow)
        ordinals = itertools.count(1)
        for batch in source.iter_batches(batch_size=_batch_size(source, options.parquet_row_group_bytes)):
            for values in batch.to_pylist():
                yield SourceRow(values, next(ordinals))


def scan_types(spec: InputSpec, _options: ReadOptions, _ignore_nulls: bool) -> Candidates:
    """Report each column's candidate types straight from the Parquet schema."""
    with _open(spec) as source:
        schema = source.schema_arrow
        _reject_nested(spec, schema)
        return {field.name: _candidates(field.type) for field in schema}


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


def _reject_nested(spec: InputSpec, schema: pyarrow.Schema) -> None:
    """Reject the list, map and struct columns that only a schema can describe."""
    nested = [field.name for field in schema if arrow_types.is_nested(field.type)]
    if nested:
        raise NestedDataError(
            f"nested structure requires provided --schema"
            f" in column(s) {', '.join(nested)} (file={spec.path})"
        )


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

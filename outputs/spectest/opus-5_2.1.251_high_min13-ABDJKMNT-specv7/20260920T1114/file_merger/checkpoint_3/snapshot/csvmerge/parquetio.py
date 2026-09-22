"""Reading Parquet input one record batch at a time.

The file is never materialised: batches are pulled row group–wise, sized from the
advisory `--parquet-row-group-bytes` budget and capped so that a batch stays small
next to the memory limit. Nested columns are rejected from the schema alone, before
any row is read (ambiguity T32).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import BinaryIO, Iterator

import pyarrow
import pyarrow.parquet as pq
import pyarrow.types

from csvmerge.errors import EXIT_INPUT, EXIT_NESTED, MergeError

DEFAULT_ROW_GROUP_BYTES = 8 * 1024 * 1024

# Upper bound on one batch, so that a tiny average row does not turn the byte
# budget into millions of Python dictionaries at once.
_MAX_BATCH_ROWS = 65536


@contextmanager
def open_parquet(
    handle: BinaryIO, path: str, row_group_bytes: int
) -> Iterator[tuple[list[str], Iterator[dict[str, object]]]]:
    """Yield the column names and streamed records of a Parquet input."""
    try:
        parquet = pq.ParquetFile(handle)
    except pyarrow.ArrowInvalid as error:
        raise MergeError(
            f"{path}: not a readable Parquet file: {error}", EXIT_INPUT
        ) from error
    schema = parquet.schema_arrow
    _reject_nested(schema, path)
    yield schema.names, _records(parquet, _batch_rows(parquet.metadata, row_group_bytes))


def _reject_nested(schema, path: str) -> None:
    nested = [field.name for field in schema if pyarrow.types.is_nested(field.type)]
    if nested:
        raise MergeError(
            f"{path}: nested Parquet column(s): {', '.join(nested)}", EXIT_NESTED
        )


def _batch_rows(metadata, row_group_bytes: int) -> int:
    """Translate the advisory byte budget into a row count for `iter_batches`."""
    if not metadata.num_rows:
        return 1
    uncompressed = sum(
        metadata.row_group(index).total_byte_size
        for index in range(metadata.num_row_groups)
    )
    average = max(1, uncompressed // metadata.num_rows)
    return max(1, min(row_group_bytes // average, _MAX_BATCH_ROWS))


def _records(parquet, batch_rows: int) -> Iterator[dict[str, object]]:
    for batch in parquet.iter_batches(batch_size=batch_rows):
        yield from batch.to_pylist()

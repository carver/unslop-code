"""Reading Parquet inputs one batch of rows at a time.

Kept apart from the other formats so that pyarrow - which is expensive to
import - is only loaded by a merge that actually has a Parquet input.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import FrozenSet, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from csvmerge.errors import EXIT_NESTED, MergeError
from csvmerge.formats import FormatSpec, open_binary
from csvmerge.sources import Row, Source
from csvmerge.values import WIDENINGS

# Parquet types that map onto a column type; anything else is read as text.
_ARROW_TYPES = (
    (pa.types.is_boolean, "bool"),
    (pa.types.is_integer, "int"),
    (pa.types.is_floating, "float"),
    (pa.types.is_decimal, "float"),
    (pa.types.is_date, "date"),
    (pa.types.is_timestamp, "timestamp"),
)


class ParquetSource(Source):
    """Parquet, streamed one batch of rows at a time.

    The file states its own column types, so resolving a schema needs no pass
    over the data and the inference mode does not apply. Nested columns -
    lists, maps, structs - are rejected.
    """

    typed = True

    def __init__(self, path: str, spec: FormatSpec, row_group_bytes: int) -> None:
        super().__init__(path, spec)
        self._row_group_bytes = row_group_bytes

    def observe_types(self, mode: str) -> dict[str, FrozenSet[str] | None]:
        """Read the types off the file's own schema; there is nothing to narrow."""
        with self._open() as reader:
            return {
                name: WIDENINGS[type_name]
                for name, type_name in _flat_types(self.path, reader.schema_arrow).items()
            }

    def rows(self) -> Iterator[Row]:
        with self._open() as reader:
            _flat_types(self.path, reader.schema_arrow)  # nested columns, rejected up front
            ordinal = 1
            batch_rows = _batch_rows(reader.metadata, self._row_group_bytes)
            # Decoding one column at a time keeps the working set to a single
            # batch; the Python loop below is the bottleneck either way.
            for batch in reader.iter_batches(batch_size=batch_rows, use_threads=False):
                for values in batch.to_pylist():
                    yield Row(ordinal, values)
                    ordinal += 1

    @contextmanager
    def _open(self) -> Iterator[pq.ParquetFile]:
        with open_binary(self.path, self.spec.compression) as handle:
            # Read-ahead would hold whole row groups for a reader that only
            # ever moves forwards.
            yield pq.ParquetFile(handle, pre_buffer=False)


def _flat_types(path: str, schema: pa.Schema) -> dict[str, str]:
    """Name the column type of every Parquet field, rejecting nested ones."""
    return {field.name: _column_type(path, field) for field in schema}


def _column_type(path: str, field: pa.Field) -> str:
    if pa.types.is_nested(field.type):
        raise MergeError(
            f"{path}: column {field.name!r} has the nested type {field.type}; "
            "only flat Parquet schemas are supported",
            EXIT_NESTED,
        )
    for matches, type_name in _ARROW_TYPES:
        if matches(field.type):
            return type_name
    return "string"


def _batch_rows(metadata: pq.FileMetaData, row_group_bytes: int) -> int:
    """Rows per batch, so that roughly ``row_group_bytes`` are decoded at once."""
    if not metadata.num_rows:
        return 1
    stored = sum(metadata.row_group(index).total_byte_size for index in range(metadata.num_row_groups))
    return max(1, int(row_group_bytes * metadata.num_rows / stored))

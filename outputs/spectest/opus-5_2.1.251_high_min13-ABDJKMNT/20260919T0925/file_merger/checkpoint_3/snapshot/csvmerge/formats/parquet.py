"""Parquet sources, read one batch of rows at a time."""

from __future__ import annotations

from contextlib import contextmanager

import pyarrow.parquet as pq
from pyarrow import types

from ..errors import NestedDataError
from ..values import native
from .detect import open_binary


class ParquetSource:
    """A Parquet input with a flat schema.

    The file is never materialized: `iter_batches` walks it row group by row group,
    and `--parquet-row-group-bytes` is the advisory budget one batch should occupy
    (AMBIGUITIES T30). A declared schema makes this the most authoritative source of
    column types (T19).
    """

    tier = 3

    def __init__(self, path, compression, batch_bytes):
        self.path = path
        self._compression = compression
        self._batch_bytes = batch_bytes

    def fields(self):
        """The column names declared by the file's schema."""
        with self._open() as parquet:
            return tuple(parquet.schema_arrow.names)

    def records(self):
        """Yield ``(origin, {column: value})`` for every row, batch by batch."""
        with self._open() as parquet:
            number = 0
            for batch in parquet.iter_batches(batch_size=self._batch_rows(parquet)):
                for row in batch.to_pylist():
                    number += 1
                    yield f"{self.path}:row {number}", {n: native(v) for n, v in row.items()}

    @contextmanager
    def _open(self):
        """Yield the opened file, having rejected any nested column first."""
        with open_binary(self.path, self._compression) as stream:
            parquet = pq.ParquetFile(stream)
            self._reject_nested(parquet.schema_arrow)
            yield parquet

    def _reject_nested(self, schema):
        for field in schema:
            if types.is_nested(field.type):
                raise NestedDataError(f"{self.path}: column {field.name!r} has nested type {field.type}")

    def _batch_rows(self, parquet):
        """Translate the advisory byte budget into a row count for one batch."""
        metadata = parquet.metadata
        groups = (metadata.row_group(index) for index in range(metadata.num_row_groups))
        stored_bytes = sum(group.total_byte_size for group in groups)
        row_bytes = max(1, stored_bytes // max(1, metadata.num_rows))
        return max(1, self._batch_bytes // row_bytes)

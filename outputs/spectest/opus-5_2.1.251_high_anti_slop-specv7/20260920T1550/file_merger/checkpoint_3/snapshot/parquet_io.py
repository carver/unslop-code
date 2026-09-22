"""Reading Parquet inputs, one row group at a time.

Only flat schemas are supported: a list, struct or map column cannot be written
to a CSV cell and is reported instead.  Column types come from the file's own
schema, so a Parquet file never has to be read twice, and rows are materialised
in batches sized by ``--parquet-row-group-bytes`` so that a file of any size
costs the same memory.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from column_types import Record, narrow_number
from errors import SchemaError
from inference import Candidates
from streams import open_binary

# Errors pyarrow raises for a file that is not valid Parquet.
PARQUET_ERRORS = (pa.ArrowInvalid,)

# Rough cost of one cell once a batch has been turned into Python objects: a
# short object plus its slot in the row's dict.  The stored size of a row says
# little about that, so the byte budget is spent against both.
_PER_CELL_OVERHEAD = 128

# Which output types a Parquet column can be cast to, by its Arrow type.
_TYPE_CANDIDATES = (
    (pa.types.is_boolean, frozenset({"bool", "string"})),
    (pa.types.is_integer, frozenset({"int", "float", "string"})),
    (pa.types.is_floating, frozenset({"float", "string"})),
    (pa.types.is_decimal, frozenset({"float", "string"})),
    (pa.types.is_date, frozenset({"date", "string"})),
    (pa.types.is_timestamp, frozenset({"timestamp", "string"})),
)


class ParquetReader:
    """A Parquet input, streamed row group by row group."""

    format = "parquet"

    def __init__(self, path: Path, compression: str, row_group_bytes: int) -> None:
        self._path = path
        self._compression = compression
        self._row_group_bytes = row_group_bytes

    def records(self) -> Iterator[Record]:
        """Stream the rows of the file as records of already typed values."""
        with self._open() as parquet:
            for batch in parquet.iter_batches(batch_size=self._batch_rows(parquet)):
                for row in batch.to_pylist():
                    yield {name: narrow_number(value) for name, value in row.items()}

    def scan(self) -> Candidates:
        """Read the column types straight from the file's schema."""
        with self._open() as parquet:
            return {field.name: _candidates(field.type) for field in parquet.schema_arrow}

    @contextmanager
    def _open(self) -> Iterator[pq.ParquetFile]:
        """Open the file and reject any column that is not a flat scalar."""
        with open_binary(self._path, self._compression) as handle:
            parquet = pq.ParquetFile(handle)
            nested = sorted(
                field.name for field in parquet.schema_arrow if pa.types.is_nested(field.type)
            )
            if nested:
                raise SchemaError(
                    f"{self._path}: column(s) {', '.join(nested)} are not flat; "
                    "Parquet lists, structs and maps cannot be merged"
                )
            yield parquet

    def _batch_rows(self, parquet: pq.ParquetFile) -> int:
        """How many rows to materialise at once for the advisory byte budget."""
        metadata = parquet.metadata
        stored = sum(
            metadata.row_group(index).total_byte_size for index in range(metadata.num_row_groups)
        )
        stored_per_row = stored // metadata.num_rows if metadata.num_rows else 0
        per_row = max(stored_per_row + _PER_CELL_OVERHEAD * metadata.num_columns, 1)
        return max(self._row_group_bytes // per_row, 1)


def _candidates(arrow_type: pa.DataType) -> set[str]:
    """Which output types a column of this Arrow type can be cast to."""
    for matches, types in _TYPE_CANDIDATES:
        if matches(arrow_type):
            return set(types)
    return {"string"}

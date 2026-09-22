"""Reading parquet inputs, one row group batch at a time.

Parquet is the only source that carries its own schema, so it both declares
column types for schema resolution and hands back typed values. Nested columns
are rejected as soon as the schema is read, whether or not the merge would have
selected them.
"""

from __future__ import annotations

from contextlib import contextmanager

import pyarrow as pa
import pyarrow.parquet as pq

from .errors import NestedValueError
from .records import Record, RecordStream, text_of

#: Tried in order; anything unrecognised is treated as text.
_TYPE_TESTS = (
    (pa.types.is_boolean, "bool"),
    (pa.types.is_integer, "int"),
    (pa.types.is_floating, "float"),
    (pa.types.is_decimal, "float"),
    (pa.types.is_timestamp, "timestamp"),
    (pa.types.is_date, "date"),
)

#: Bounds on the advisory batch size, so that a tiny or huge byte budget still
#: yields a workable number of rows per batch.
_MIN_BATCH_ROWS, _MAX_BATCH_ROWS = 1, 100_000


@contextmanager
def open_parquet(spec):
    """Yield the records of one parquet input, batch by batch."""
    with spec.open_binary() as handle:
        reader = pq.ParquetFile(handle)
        names = tuple(_flat_schema(spec, reader).names)
        yield RecordStream(names, _records(reader, names, _batch_rows(reader.metadata, spec.batch_bytes)))


def declared_types(spec) -> dict[str, str]:
    """The schema type of each column, in this tool's type vocabulary."""
    with spec.open_binary() as handle:
        schema = _flat_schema(spec, pq.ParquetFile(handle))
    return {field.name: _type_name(field.type) for field in schema}


def _flat_schema(spec, reader) -> pa.Schema:
    """The file's arrow schema, rejecting list, struct and map columns."""
    schema = reader.schema_arrow
    nested = [field.name for field in schema if pa.types.is_nested(field.type)]
    if nested:
        raise NestedValueError(f"{spec.path}: nested parquet column(s) {', '.join(nested)}")
    return schema


def _type_name(arrow_type) -> str:
    for test, name in _TYPE_TESTS:
        if test(arrow_type):
            return name
    return "string"


def _batch_rows(metadata, batch_bytes: int) -> int:
    """Turn the advisory byte budget into a row count for ``iter_batches``."""
    if not metadata.num_rows:
        return _MIN_BATCH_ROWS
    uncompressed = sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))
    row_bytes = max(1, uncompressed // metadata.num_rows)
    return max(_MIN_BATCH_ROWS, min(_MAX_BATCH_ROWS, batch_bytes // row_bytes))


def _records(reader, names: tuple[str, ...], batch_rows: int):
    position = 0
    for batch in reader.iter_batches(batch_size=batch_rows):
        columns = [column.to_pylist() for column in batch.columns]
        for values in zip(*columns):
            position += 1
            yield Record(names, [text_of(value) for value in values], position)

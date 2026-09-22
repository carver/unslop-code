"""Reading parquet inputs, one row group batch at a time.

Parquet is the only source that carries its own schema, so it both declares
column types for schema resolution and hands back typed values. Nested columns
need a ``--schema`` to say what shape to expect: without one they are rejected
as soon as the file's schema is read, whether or not the merge would have
selected them.
"""

from __future__ import annotations

from contextlib import contextmanager

import pyarrow as pa
import pyarrow.parquet as pq

from .errors import NestedValueError
from .jsonl import NESTED_WITHOUT_SCHEMA
from .records import JsonValue, Record, RecordStream, text_of

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

#: A map column reads back as a JSON object; a repeated key keeps its last value.
_MAPS_AS_DICTS = "lossy"


@contextmanager
def open_parquet(spec, nested_ok: bool):
    """Yield the records of one parquet input, batch by batch."""
    with spec.open_binary() as handle:
        reader = pq.ParquetFile(handle)
        names = tuple(_schema_of(spec, reader, nested_ok).names)
        yield RecordStream(names, _records(reader, names, _batch_rows(reader.metadata, spec.batch_bytes)))


def declared_types(spec) -> dict[str, str]:
    """The schema type of each column, in this tool's type vocabulary."""
    with spec.open_binary() as handle:
        schema = _schema_of(spec, pq.ParquetFile(handle), nested_ok=False)
    return {field.name: _type_name(field.type) for field in schema}


def _schema_of(spec, reader, nested_ok: bool) -> pa.Schema:
    """The file's arrow schema, rejecting nesting when no schema declares it."""
    schema = reader.schema_arrow
    if not nested_ok and any(pa.types.is_nested(field.type) for field in schema):
        raise NestedValueError(NESTED_WITHOUT_SCHEMA)
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
        columns = [column.to_pylist(maps_as_pydicts=_MAPS_AS_DICTS) for column in batch.columns]
        for values in zip(*columns):
            position += 1
            yield Record(names, [_cell(value) for value in values], position)


def _cell(value):
    """One parquet value: a nested one as JSON, a scalar as its text."""
    if isinstance(value, (dict, list)):
        return JsonValue(_decoded(value))
    return text_of(value)


def _decoded(value):
    """Replace the arrow values inside a nested one by the text casting expects."""
    if isinstance(value, dict):
        return {key: _decoded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decoded(item) for item in value]
    return value if isinstance(value, (bool, int, float)) or value is None else text_of(value)

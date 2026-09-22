"""Streaming Parquet input, one record batch at a time.

Only the footer is read to resolve the schema, and row groups are decoded
batch-wise, so a file far larger than the memory limit still flows through.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pyarrow.parquet as pq
from pyarrow import types as arrow_types

from .errors import EXIT_NESTED, MergeError, NESTED_REFUSAL
from .formats import InputFile, Source, open_binary

#: Arrow type predicates in the order they are tried; anything unmatched is text.
_SPEC_TYPE_TESTS = (
    (arrow_types.is_boolean, "bool"),
    (arrow_types.is_integer, "int"),
    (arrow_types.is_floating, "float"),
    (arrow_types.is_date, "date"),
    (arrow_types.is_timestamp, "timestamp"),
)


@contextmanager
def open_parquet(source: InputFile, row_group_bytes: int | None, nested_allowed: bool):
    """Open a Parquet input and yield its declared columns and streamed rows."""
    with open_binary(source) as handle:
        reader = pq.ParquetFile(handle)
        declared = _declared_types(reader, nested_allowed)
        yield Source(tuple(declared), _stream(reader, row_group_bytes), True, declared)


def _declared_types(reader: pq.ParquetFile, nested_allowed: bool) -> dict[str, str]:
    """Map the file's Arrow schema onto the six schema types.

    A nested column has no primitive type to declare, so it is refused unless a
    `--schema` says what it is; when one does, inference is not running and
    these declared types are not read.
    """
    types = {}
    for field in reader.schema_arrow:
        if not arrow_types.is_nested(field.type):
            types[field.name] = _spec_type(field.type)
        elif not nested_allowed:
            raise MergeError(NESTED_REFUSAL, EXIT_NESTED)
    return types


def _spec_type(arrow_type) -> str:
    for test, name in _SPEC_TYPE_TESTS:
        if test(arrow_type):
            return name
    return "string"


def _stream(reader: pq.ParquetFile, row_group_bytes: int | None) -> Iterator[dict]:
    """Yield every row as a mapping, decoding one batch at a time."""
    sizing = {} if row_group_bytes is None else {"batch_size": _batch_rows(reader, row_group_bytes)}
    for batch in reader.iter_batches(**sizing):
        # Arrow maps decode to key/value pair lists by default; as dicts they
        # cast like every other mapping.
        yield from batch.to_pylist(maps_as_pydicts="lossy")


def _batch_rows(reader: pq.ParquetFile, row_group_bytes: int) -> int:
    """Turn the advisory byte budget into a row count, via the file's own row size."""
    metadata = reader.metadata
    encoded = sum(
        metadata.row_group(index).total_byte_size for index in range(metadata.num_row_groups)
    )
    bytes_per_row = max(1, encoded // max(1, metadata.num_rows))
    return max(1, row_group_bytes // bytes_per_row)

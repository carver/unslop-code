"""Input sources: detect each file's format, then read it with the matching reader.

Every source exposes the same three things — `fields()` for the column names it
declares up front, `records()` for its rows, and a `tier` giving the precedence of
its type information under `--schema-strategy=authoritative`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..dialect import CsvDialect
from .delimited import CsvSource, TsvSource
from .detect import (
    AUTO,
    COMPRESSIONS,
    CSV,
    INPUT_FORMATS,
    JSONL,
    PARQUET,
    TSV,
    resolve_compression,
    resolve_format,
)
from .jsonl import JsonlSource
from .parquet import ParquetSource

#: Advisory default for `--parquet-row-group-bytes`: big enough to amortize batch
#: overhead, small enough to stay well inside a 64 MB memory limit.
DEFAULT_PARQUET_BATCH_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class InputOptions:
    """What the command line says about reading inputs."""

    dialect: CsvDialect = field(default_factory=CsvDialect)
    input_format: str = AUTO
    compression: str = AUTO
    parquet_batch_bytes: int = DEFAULT_PARQUET_BATCH_BYTES
    #: Nested input is only readable when a `--schema` declares its shape.
    allow_nested: bool = False


_SOURCES = {
    CSV: lambda path, compression, options: CsvSource(path, compression, options.dialect),
    TSV: lambda path, compression, options: TsvSource(path, compression),
    JSONL: lambda path, compression, options: JsonlSource(path, compression, options.allow_nested),
    PARQUET: lambda path, compression, options: ParquetSource(
        path, compression, options.parquet_batch_bytes, options.allow_nested
    ),
}


def open_source(path, options):
    """Return the reader for `path`, detecting format and compression as needed."""
    compression = resolve_compression(path, options.compression)
    input_format = resolve_format(path, options.input_format, compression)
    return _SOURCES[input_format](path, compression, options)


__all__ = [
    "COMPRESSIONS",
    "DEFAULT_PARQUET_BATCH_BYTES",
    "INPUT_FORMATS",
    "InputOptions",
    "open_source",
]

"""Dispatch from an input's format to the reader that decodes it."""

from __future__ import annotations

from typing import Callable, Iterator

from . import csvio, jsonlio
from .datatypes import DataType
from .formats import FileFormat, InputRow, Source

_ROW_READERS: dict[FileFormat, Callable[[Source], Iterator[InputRow]]] = {
    FileFormat.CSV: csvio.read_rows,
    FileFormat.TSV: csvio.read_rows,
    FileFormat.JSONL: jsonlio.read_rows,
}

_HEADER_FORMATS = frozenset({FileFormat.CSV, FileFormat.TSV})


def rows(source: Source) -> Iterator[InputRow]:
    """Yield every record of one input, in file order."""
    if source.format is FileFormat.PARQUET:
        return _parquet().read_rows(source)
    return _ROW_READERS[source.format](source)


def declared_types(source: Source) -> dict[str, DataType] | None:
    """Column types the input states up front, or ``None`` if it states none."""
    if source.format is FileFormat.PARQUET:
        return _parquet().read_types(source)
    return None


def header_names(source: Source) -> tuple[str, ...]:
    """Column names from a header row; empty for formats that have none."""
    if source.format in _HEADER_FORMATS:
        return csvio.read_header(source)
    return ()


def _parquet():
    """Load the Parquet reader on demand, so runs without it never import Arrow."""
    from . import parquetio

    return parquetio

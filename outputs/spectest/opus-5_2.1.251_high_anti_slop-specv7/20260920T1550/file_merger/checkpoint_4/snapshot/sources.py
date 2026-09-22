"""Deciding what each input is and handing back a reader for it.

``--input-format=auto`` names the format from the file extension, allowing a
``.gz`` suffix after it, and falls back to sniffing the Parquet magic bytes
when the extension says nothing.  ``--compression=auto`` goes by the ``.gz``
suffix.  Every reader returned from here answers the same two questions:
``scan()`` for the types of its columns and ``records()`` for its rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from csv_io import CsvOptions, CsvReader, TsvReader
from errors import UsageError
from inference import Candidates
from jsonl_io import JsonlReader
from parquet_io import ParquetReader
from records import SourceRecord
from streams import GZIP_SUFFIX, head, resolve_compression

FORMATS = ("csv", "tsv", "jsonl", "parquet")
COMPRESSIONS = ("none", "gzip")

_EXTENSION_FORMATS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}
_PARQUET_MAGIC = b"PAR1"


class Reader(Protocol):
    """What the pipeline needs from an input, whatever its format."""

    format: str

    def scan(self) -> Candidates:
        """Return the types each of the input's columns is compatible with."""

    def records(self) -> Iterator[SourceRecord]:
        """Stream the input's rows, with the origin to report errors against."""


@dataclass(frozen=True)
class ReadOptions:
    """Everything the readers need beyond the file itself.

    ``allow_nested`` is what ``--schema`` buys: without it nothing says what an
    array or an object in an input should be cast to, so it is rejected.
    """

    csv: CsvOptions
    parquet_row_group_bytes: int
    allow_nested: bool


_READERS: dict[str, Callable[[Path, str, ReadOptions], Reader]] = {
    "csv": lambda path, compression, options: CsvReader(path, compression, options.csv),
    "tsv": lambda path, compression, options: TsvReader(path, compression, options.csv),
    "jsonl": lambda path, compression, options: JsonlReader(
        path, compression, options.allow_nested
    ),
    "parquet": lambda path, compression, options: ParquetReader(
        path, compression, options.parquet_row_group_bytes, options.allow_nested
    ),
}


def open_source(path: Path, input_format: str, compression: str, options: ReadOptions) -> Reader:
    """Resolve ``path``'s compression and format and build its reader."""
    resolved_compression = resolve_compression(path, compression)
    resolved_format = _resolve_format(path, input_format, resolved_compression)
    return _READERS[resolved_format](path, resolved_compression, options)


def _resolve_format(path: Path, requested: str, compression: str) -> str:
    if requested != "auto":
        return requested
    name = path.name.removesuffix(GZIP_SUFFIX)
    by_extension = _EXTENSION_FORMATS.get(Path(name).suffix.lower())
    if by_extension:
        return by_extension
    if head(path, compression, len(_PARQUET_MAGIC)) == _PARQUET_MAGIC:
        return "parquet"
    raise UsageError(
        f"{path}: cannot tell the input format from the extension or the contents; "
        "pass --input-format"
    )

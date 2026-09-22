"""Deciding what each input is - its format and its compression - and opening it.

Detection looks at the file name first and falls back to the magic bytes, so
``data.csv.gz`` is a gzipped CSV while an extension-less file starting with
``PAR1`` is Parquet. Whatever compression is settled on is checked against the
file's first bytes, so a mismatch is reported rather than read as garbage.
"""

from __future__ import annotations

import gzip
import io
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

from csvmerge.errors import EXIT_FORMAT, EXIT_SOURCE, MergeError

AUTO = "auto"

CSV = "csv"
TSV = "tsv"
JSONL = "jsonl"
PARQUET = "parquet"
INPUT_FORMATS = (AUTO, CSV, TSV, JSONL, PARQUET)

NO_COMPRESSION = "none"
GZIP = "gzip"
COMPRESSIONS = (AUTO, NO_COMPRESSION, GZIP)

_BY_EXTENSION = {
    ".csv": CSV,
    ".tsv": TSV,
    ".jsonl": JSONL,
    ".ndjson": JSONL,
    ".parquet": PARQUET,
}
_GZIP_SUFFIX = ".gz"
_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"


@dataclass(frozen=True)
class FormatSpec:
    """How one input is to be read."""

    format: str
    compression: str


def resolve_format(path: str, requested_format: str, requested_compression: str) -> FormatSpec:
    """Settle the format and compression of ``path``, honouring explicit requests."""
    compression = _resolve_compression(path, requested_compression)
    _reject_compression_mismatch(path, compression)
    if requested_format != AUTO:
        return FormatSpec(requested_format, compression)
    return FormatSpec(_detect_format(path, compression), compression)


@contextmanager
def open_binary(path: str, compression: str) -> Iterator[BinaryIO]:
    """Open an input as bytes, transparently decompressing a gzipped one."""
    opener = gzip.open if compression == GZIP else open
    with opener(path, "rb") as handle:
        yield handle


@contextmanager
def open_text(path: str, compression: str) -> Iterator[TextIO]:
    """Open an input as UTF-8 text, leaving line endings for the caller to handle."""
    with open_binary(path, compression) as raw:
        yield io.TextIOWrapper(raw, encoding="utf-8", newline="")


def _resolve_compression(path: str, requested: str) -> str:
    if requested != AUTO:
        return requested
    return GZIP if path.lower().endswith(_GZIP_SUFFIX) else NO_COMPRESSION


def _reject_compression_mismatch(path: str, compression: str) -> None:
    """Refuse a file whose leading bytes contradict the compression we settled on."""
    with open(path, "rb") as handle:
        compressed = handle.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    if compressed != (compression == GZIP):
        carries = "is gzipped" if compressed else "is not gzipped"
        raise MergeError(f"{path}: {carries} but compression was resolved to {compression}", EXIT_SOURCE)


def _detect_format(path: str, compression: str) -> str:
    """Name the format from the extension, falling back to the Parquet magic bytes."""
    name = Path(path)
    if name.suffix.lower() == _GZIP_SUFFIX:
        name = name.with_suffix("")
    extension = name.suffix.lower()
    if extension in _BY_EXTENSION:
        return _BY_EXTENSION[extension]
    with open_binary(path, compression) as handle:
        if handle.read(len(_PARQUET_MAGIC)) == _PARQUET_MAGIC:
            return PARQUET
    raise MergeError(
        f"{path}: cannot tell the input format from {extension or 'the file name'!r}; "
        "pass --input-format",
        EXIT_FORMAT,
    )

"""Deciding, per input file, which format it holds and how it is compressed.

Detection is by extension first and magic bytes second: a recognised extension
decides on its own, anything else is ambiguous and only Parquet's magic can
rescue it (ambiguity T38). The declared compression is always checked against the
file's first bytes, in both directions (ambiguity T29).
"""

from __future__ import annotations

import gzip
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from csvmerge.errors import EXIT_ERROR, EXIT_INPUT, EXIT_USAGE, MergeError

AUTO = "auto"
CSV = "csv"
TSV = "tsv"
JSONL = "jsonl"
PARQUET = "parquet"
FORMATS = (CSV, TSV, JSONL, PARQUET)

NONE = "none"
GZIP = "gzip"
COMPRESSIONS = (NONE, GZIP)

_EXTENSIONS = {
    ".csv": CSV,
    ".tsv": TSV,
    ".jsonl": JSONL,
    ".ndjson": JSONL,
    ".parquet": PARQUET,
}
_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"


def resolve(path: str, forced_format: str, forced_compression: str) -> tuple[str, str]:
    """Return the (format, compression) pair one input file is to be read with."""
    compression = _compression_of(path, forced_compression)
    _check_compression(path, compression)
    if forced_format != AUTO:
        return forced_format, compression
    return _format_of(path, compression), compression


@contextmanager
def open_binary(path: str, compression: str) -> Iterator[BinaryIO]:
    """Open an input as a byte stream, transparently decompressing gzip."""
    opener = gzip.open if compression == GZIP else open
    try:
        handle = opener(path, "rb")
    except OSError as error:
        raise MergeError(f"cannot read input {path}: {error}", EXIT_ERROR) from error
    with handle:
        yield handle


def _compression_of(path: str, forced: str) -> str:
    if forced != AUTO:
        return forced
    return GZIP if path.lower().endswith(".gz") else NONE


def _check_compression(path: str, compression: str) -> None:
    """Reject a file whose first bytes disagree with the compression in force."""
    with open_binary(path, NONE) as handle:
        compressed = handle.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    if compressed != (compression == GZIP):
        expected = "gzip" if compression == GZIP else "uncompressed"
        raise MergeError(f"{path}: not {expected} data", EXIT_INPUT)


def _format_of(path: str, compression: str) -> str:
    """The format of `path`, from its extension or, failing that, its magic bytes.

    A trailing `.gz` is a compression suffix rather than a format, whether or not
    the file turned out to be compressed, so the base extension decides.
    """
    name = path[: -len(".gz")] if path.lower().endswith(".gz") else path
    extension = Path(name).suffix.lower()
    if extension in _EXTENSIONS:
        return _EXTENSIONS[extension]
    with open_binary(path, compression) as handle:
        if handle.read(len(_PARQUET_MAGIC)) == _PARQUET_MAGIC:
            return PARQUET
    raise MergeError(
        f"cannot determine the format of {path}; pass --input-format", EXIT_USAGE
    )

"""Deciding how to open an input: which format it holds, and whether it is gzipped.

`--input-format` and `--compression` short-circuit the corresponding decision; on
`auto` the file name decides, with Parquet's magic bytes as the fallback for names
the extension table does not cover (AMBIGUITIES T24).
"""

from __future__ import annotations

import gzip
import io
from pathlib import PurePosixPath

from ..errors import FormatError, InputError, MergeError

AUTO = "auto"
CSV, TSV, JSONL, PARQUET = "csv", "tsv", "jsonl", "parquet"
NONE, GZIP = "none", "gzip"

#: `--input-format` and `--compression` choices, in the order the spec lists them.
INPUT_FORMATS = (AUTO, CSV, TSV, JSONL, PARQUET)
COMPRESSIONS = (AUTO, NONE, GZIP)

_BY_EXTENSION = {
    ".csv": CSV,
    ".tsv": TSV,
    ".jsonl": JSONL,
    ".ndjson": JSONL,
    ".parquet": PARQUET,
}
_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"


def resolve_compression(path, requested):
    """Return the compression to use, and reject a choice the bytes contradict."""
    chosen = requested
    if requested == AUTO:
        chosen = GZIP if path.name.endswith(".gz") else NONE
    if _leading_bytes(path, NONE, len(_GZIP_MAGIC)).startswith(_GZIP_MAGIC) != (chosen == GZIP):
        raise InputError(f"{path}: compression '{chosen}' does not match the file contents")
    return chosen


def resolve_format(path, requested, compression):
    """Return the format to read `path` as, by extension then by magic bytes."""
    if requested != AUTO:
        return requested
    base = path.name[: -len(".gz")] if path.name.endswith(".gz") else path.name
    known = _BY_EXTENSION.get(PurePosixPath(base).suffix.lower())
    if known:
        return known
    if _leading_bytes(path, compression, len(_PARQUET_MAGIC)) == _PARQUET_MAGIC:
        return PARQUET
    raise FormatError(f"{path}: cannot determine input format from its name or contents")


def open_binary(path, compression):
    """Open `path` for reading, transparently decompressing when gzipped."""
    opener = gzip.open if compression == GZIP else open
    try:
        return opener(path, "rb")
    except OSError as error:
        raise MergeError(f"cannot read input {path}: {error}") from error


def open_text(path, compression, newline=""):
    """Open `path` as UTF-8 text, transparently decompressing when gzipped."""
    return io.TextIOWrapper(open_binary(path, compression), encoding="utf-8", newline=newline)


def _leading_bytes(path, compression, count):
    with open_binary(path, compression) as stream:
        try:
            return stream.read(count)
        except OSError as error:
            raise InputError(f"{path}: cannot decompress: {error}") from error

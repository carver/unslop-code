"""Describing an input: its format, its compression and how to open it.

``describe`` turns a path plus the command line's overrides into a
:class:`Source`, which every reader takes as its single argument.  Detection
looks at the file name first and falls back to the magic bytes, and the
resolved compression is always checked against those bytes so a forced
``--compression`` that contradicts the file is reported rather than obeyed.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import IO, Any, NamedTuple

from .errors import SourceFormatError, UsageError


class FileFormat(str, Enum):
    """The input formats the tool reads; ``auto`` means "detect per file"."""

    AUTO = "auto"
    CSV = "csv"
    TSV = "tsv"
    JSONL = "jsonl"
    PARQUET = "parquet"


class Compression(str, Enum):
    """The codecs an input may be wrapped in; ``auto`` means "detect"."""

    AUTO = "auto"
    NONE = "none"
    GZIP = "gzip"


#: Precedence of a format when ``--schema-strategy=authoritative`` picks which
#: files decide a column's type.  Parquet states its types, so it outranks the
#: formats whose types have to be inferred; JSONL ranks equal to CSV and TSV.
_PRECEDENCE = {
    FileFormat.PARQUET: 0,
    FileFormat.JSONL: 1,
    FileFormat.CSV: 1,
    FileFormat.TSV: 1,
}

_EXTENSIONS = {
    ".csv": FileFormat.CSV,
    ".tsv": FileFormat.TSV,
    ".jsonl": FileFormat.JSONL,
    ".ndjson": FileFormat.JSONL,
    ".parquet": FileFormat.PARQUET,
}

_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"

#: Advisory batch budget for Parquet reads when ``--parquet-row-group-bytes``
#: is not given.
DEFAULT_ROW_GROUP_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class InputDialect:
    """How CSV cells are quoted, escaped and spelled when null."""

    quotechar: str = '"'
    escapechar: str | None = "\\"
    null_literal: str = ""

    @property
    def null_texts(self) -> frozenset[str]:
        """Cell texts read as null: the empty cell and the null literal."""
        return frozenset({"", self.null_literal})


@dataclass(frozen=True)
class Source:
    """One input file together with everything needed to decode it."""

    path: str
    format: FileFormat
    compression: Compression
    dialect: InputDialect = InputDialect()
    row_group_bytes: int = DEFAULT_ROW_GROUP_BYTES

    @property
    def rank(self) -> int:
        """Precedence of this file's format during schema resolution."""
        return _PRECEDENCE[self.format]


class InputRow(NamedTuple):
    """One record and the 1-based position in its file that it came from."""

    position: int
    values: dict[str, Any]


def describe(
    path: str,
    file_format: FileFormat,
    compression: Compression,
    dialect: InputDialect,
    row_group_bytes: int,
) -> Source:
    """Resolve ``auto`` format and compression for one input file."""
    resolved_compression = _resolve_compression(path, compression)
    resolved_format = (
        _detect_format(path, resolved_compression) if file_format is FileFormat.AUTO else file_format
    )
    return Source(path, resolved_format, resolved_compression, dialect, row_group_bytes)


def open_text(path: str, compression: Compression) -> IO[str]:
    """Open an input as decoded UTF-8 text, with newlines left untranslated."""
    if compression is Compression.GZIP:
        return gzip.open(path, mode="rt", encoding="utf-8", newline="")
    return open(path, mode="rt", encoding="utf-8", newline="")


def open_binary(path: str, compression: Compression) -> IO[bytes]:
    """Open an input as a seekable stream of decompressed bytes."""
    if compression is Compression.GZIP:
        return gzip.open(path, mode="rb")
    return open(path, mode="rb")


def _resolve_compression(path: str, requested: Compression) -> Compression:
    """Settle on a codec and make sure the file's first bytes agree with it."""
    compression = requested
    if requested is Compression.AUTO:
        compression = Compression.GZIP if path.endswith(".gz") else Compression.NONE
    with open(path, "rb") as handle:
        gzipped = handle.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    if gzipped is not (compression is Compression.GZIP):
        raise SourceFormatError(
            f"{path}: read as {compression.value} but the file "
            f"{'is' if gzipped else 'is not'} gzip compressed"
        )
    return compression


def _detect_format(path: str, compression: Compression) -> FileFormat:
    """Name the format from the extension, or from the magic bytes."""
    name = Path(path).name
    stem = name[: -len(".gz")] if name.endswith(".gz") else name
    detected = _EXTENSIONS.get(Path(stem).suffix.lower())
    if detected is not None:
        return detected
    if _is_parquet(path, compression):
        return FileFormat.PARQUET
    raise UsageError(
        f"{path}: cannot tell the format from the file name; pass --input-format"
    )


def _is_parquet(path: str, compression: Compression) -> bool:
    with open_binary(path, compression) as handle:
        return handle.read(len(_PARQUET_MAGIC)) == _PARQUET_MAGIC

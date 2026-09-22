"""Input file identity: format and compression detection, and opening the bytes."""

from __future__ import annotations

import gzip
import os
from dataclasses import dataclass
from enum import Enum
from typing import IO

from ..dialect import CsvDialect
from ..errors import FormatDetectionError, MalformedInputError


class InputFormat(str, Enum):
    """Supported input formats; ``auto`` asks for per-file detection."""

    AUTO = "auto"
    CSV = "csv"
    TSV = "tsv"
    JSONL = "jsonl"
    PARQUET = "parquet"


class Compression(str, Enum):
    AUTO = "auto"
    NONE = "none"
    GZIP = "gzip"


#: Which source a disagreement should defer to under ``--schema-strategy
#: authoritative``: formats that carry their own types outrank plain text.
FORMAT_PRECEDENCE = {
    InputFormat.CSV: 0,
    InputFormat.TSV: 0,
    InputFormat.JSONL: 1,
    InputFormat.PARQUET: 2,
}

_EXTENSIONS = {
    ".csv": InputFormat.CSV,
    ".tsv": InputFormat.TSV,
    ".jsonl": InputFormat.JSONL,
    ".ndjson": InputFormat.JSONL,
    ".parquet": InputFormat.PARQUET,
}

_GZIP_SUFFIX = ".gz"
_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"


@dataclass(frozen=True)
class InputSpec:
    """One input file with its resolved format and compression."""

    path: str
    format: InputFormat
    compression: Compression

    @property
    def precedence(self) -> int:
        return FORMAT_PRECEDENCE[self.format]


@dataclass(frozen=True)
class ReadOptions:
    """Reader settings that are the same for every input."""

    dialect: CsvDialect
    parquet_row_group_bytes: int


def detect_input(path: str, format_option: InputFormat, compression_option: Compression) -> InputSpec:
    """Resolve how ``path`` should be read, honouring any forced format or compression.

    Extensions decide first — ``.gz`` may follow the base extension — and a file
    whose extension says nothing is read as Parquet when it starts with ``PAR1``.
    """
    compression = _detect_compression(path, compression_option)
    _verify_compression(path, compression)
    return InputSpec(path, _detect_format(path, format_option, compression), compression)


def open_text(spec: InputSpec) -> IO[str]:
    """Open an input as UTF-8 text, with newline translation left to the caller."""
    return _opener(spec.compression)(spec.path, "rt", encoding="utf-8", newline="")


def open_binary(spec: InputSpec) -> IO[bytes]:
    """Open an input as a seekable stream of decompressed bytes."""
    return _opener(spec.compression)(spec.path, "rb")


def _opener(compression: Compression):
    """Return the callable that reads a file's bytes, decompressing if needed."""
    return gzip.open if compression is Compression.GZIP else open


def _detect_compression(path: str, option: Compression) -> Compression:
    if option is not Compression.AUTO:
        return option
    return Compression.GZIP if path.endswith(_GZIP_SUFFIX) else Compression.NONE


def _verify_compression(path: str, compression: Compression) -> None:
    """Reject a file whose leading bytes contradict the compression in force."""
    with open(path, "rb") as stream:
        gzipped = stream.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    if gzipped and compression is Compression.NONE:
        raise MalformedInputError(f"{path}: file is gzipped but --compression=none was requested")
    if not gzipped and compression is Compression.GZIP:
        raise MalformedInputError(f"{path}: --compression=gzip was requested but the file is not gzipped")


def _detect_format(path: str, option: InputFormat, compression: Compression) -> InputFormat:
    if option is not InputFormat.AUTO:
        return option
    base = path[: -len(_GZIP_SUFFIX)] if path.endswith(_GZIP_SUFFIX) else path
    detected = _EXTENSIONS.get(os.path.splitext(base)[1].lower())
    if detected is not None:
        return detected
    with _opener(compression)(path, "rb") as stream:
        if stream.read(len(_PARQUET_MAGIC)) == _PARQUET_MAGIC:
            return InputFormat.PARQUET
    raise FormatDetectionError(f"{path}: cannot tell the input format from its extension or contents")

"""Deciding what each input is: its format, its compression, and how to open it.

``--input-format`` and ``--compression`` either pin those answers or leave them
to be detected from the file's name and its first bytes.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import dataclass
from pathlib import Path

from .errors import DetectionError, SourceFormatError

FORMATS = ("auto", "csv", "tsv", "jsonl", "parquet")
COMPRESSIONS = ("auto", "none", "gzip")

_BY_EXTENSION = {".csv": "csv", ".tsv": "tsv", ".jsonl": "jsonl", ".ndjson": "jsonl", ".parquet": "parquet"}
_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"
_MAGIC_BYTES = 4


@dataclass(frozen=True)
class SourceSpec:
    """One resolved input: what it is and how to read its bytes."""

    path: str
    format: str
    compression: str
    #: Advisory batch budget for the parquet reader.
    batch_bytes: int

    def open_binary(self):
        """Open the file, transparently decompressing it when it is gzip."""
        return _open_binary(self.path, self.compression)

    def open_text(self):
        """Open the file as UTF-8 text with newlines left to the caller."""
        return io.TextIOWrapper(self.open_binary(), encoding="utf-8-sig", newline="")


def resolve_source(path: str, input_format: str, compression: str, batch_bytes: int) -> SourceSpec:
    """Pin down one input's format and compression, before any of it is read."""
    resolved = _resolve_compression(path, compression)
    detected = input_format if input_format != "auto" else _detect_format(path, resolved)
    return SourceSpec(path, detected, resolved, batch_bytes)


def _open_binary(path: str, compression: str):
    return gzip.open(path, "rb") if compression == "gzip" else open(path, "rb")


def _resolve_compression(path: str, requested: str) -> str:
    """Apply, or detect, the compression, rejecting a contradicted setting.

    The magic bytes are the authority: a forced setting that disagrees with them
    is the mismatch the spec assigns error 5, and so is a ``.gz`` name whose
    content is not gzip. A gzip body under another name is simply detected as
    gzip (see AMBIGUITIES T23).
    """
    with open(path, "rb") as handle:
        is_gzip = handle.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC

    if requested == "auto":
        if path.endswith(".gz") and not is_gzip:
            raise SourceFormatError(f"{path}: named as gzip but its content is not gzip")
        return "gzip" if is_gzip else "none"

    if (requested == "gzip") != is_gzip:
        raise SourceFormatError(f"{path}: --compression={requested} contradicts the file's content")
    return requested


def _detect_format(path: str, compression: str) -> str:
    """Name the format from the extension, falling back to the parquet magic.

    Only an unrecognised extension is "ambiguous" enough to look inside the
    file, and then only for parquet (see AMBIGUITIES T24).
    """
    base = path[: -len(".gz")] if path.endswith(".gz") else path
    by_extension = _BY_EXTENSION.get(Path(base).suffix.lower())
    if by_extension:
        return by_extension

    with _open_binary(path, compression) as handle:
        if handle.read(_MAGIC_BYTES) == _PARQUET_MAGIC:
            return "parquet"
    raise DetectionError(f"{path}: cannot tell the input format from its name or content")

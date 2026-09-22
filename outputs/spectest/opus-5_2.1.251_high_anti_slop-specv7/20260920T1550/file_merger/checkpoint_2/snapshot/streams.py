"""Opening an input file, transparently decompressing gzip.

Compression is settled before anything reads the file so that a name, or an
explicit ``--compression``, that contradicts the bytes on disk is reported
rather than half-read.
"""

from __future__ import annotations

import gzip
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

from errors import DataError

GZIP_MAGIC = b"\x1f\x8b"
GZIP_SUFFIX = ".gz"


def resolve_compression(path: Path, requested: str) -> str:
    """Return ``"gzip"`` or ``"none"`` for ``path``, checking the file agrees.

    ``auto`` goes by the ``.gz`` suffix.  Either way the first bytes of the
    file have to match the answer.
    """
    expected = requested if requested != "auto" else _by_name(path)
    if _is_gzipped(path) != (expected == "gzip"):
        raise DataError(f"{path}: contents do not match {expected} compression")
    return expected


def head(path: Path, compression: str, size: int) -> bytes:
    """Read the first ``size`` decompressed bytes, for magic byte sniffing."""
    with open_binary(path, compression) as handle:
        return handle.read(size)


@contextmanager
def open_text(path: Path, compression: str) -> Iterator[TextIO]:
    """Open ``path`` as UTF-8 text with the line endings left untouched."""
    opener = gzip.open if compression == "gzip" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        yield handle


@contextmanager
def open_binary(path: Path, compression: str) -> Iterator[BinaryIO]:
    """Open ``path`` as a seekable stream of decompressed bytes."""
    opener = gzip.open if compression == "gzip" else open
    with opener(path, "rb") as handle:
        yield handle


def _by_name(path: Path) -> str:
    return "gzip" if path.name.endswith(GZIP_SUFFIX) else "none"


def _is_gzipped(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(GZIP_MAGIC)) == GZIP_MAGIC

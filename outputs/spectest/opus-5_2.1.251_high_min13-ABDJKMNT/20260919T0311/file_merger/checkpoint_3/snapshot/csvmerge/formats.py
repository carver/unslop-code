"""What each input is: its format, its compression, and how to open its bytes.

Detection happens once per input, before anything is read, so that a run fails
on a misdescribed file rather than half way through parsing it.
"""
from __future__ import annotations

import gzip
import io
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import EXIT_SOURCE, EXIT_USAGE, MergeError

_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"

_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}


@dataclass(frozen=True)
class InputFile:
    """One input path with its format and compression already decided."""

    path: str
    format: str
    compression: str


@dataclass(frozen=True)
class Source:
    """An opened input: the columns it is known to have, and its rows.

    `rows` yields `{column: value}` mappings. Values are raw text for CSV and
    TSV, and native Python objects for the typed formats. `declared` carries a
    format's own column types when it publishes them, which is everything schema
    inference needs from a Parquet footer.
    """

    columns: tuple[str, ...]
    rows: Iterator[dict]
    typed: bool
    declared: dict[str, str] | None = None
    first_row: int = 1


def resolve_input(path: str, format_request: str, compression_request: str) -> InputFile:
    """Decide how `path` will be read, honouring any forced format or compression."""
    compression = _compression_of(path, compression_request)
    _check_compression(path, compression)
    if format_request != "auto":
        return InputFile(path, format_request, compression)
    return InputFile(path, _format_of(path, compression), compression)


@contextmanager
def open_binary(source: InputFile):
    """Open the input's decompressed byte stream."""
    opener = gzip.open if source.compression == "gzip" else open
    with opener(source.path, "rb") as handle:
        yield handle


@contextmanager
def open_text(source: InputFile, newline: str):
    """Open the input as UTF-8 text; a leading BOM is tolerated and dropped."""
    with open_binary(source) as raw:
        yield io.TextIOWrapper(raw, encoding="utf-8-sig", newline=newline)


def _compression_of(path: str, request: str) -> str:
    if request != "auto":
        return request
    return "gzip" if path.endswith(".gz") else "none"


def _check_compression(path: str, compression: str) -> None:
    """Reject a file whose first bytes contradict the compression it was given."""
    with open(path, "rb") as handle:
        is_gzip = handle.read(len(_GZIP_MAGIC)) == _GZIP_MAGIC
    if is_gzip != (compression == "gzip"):
        found = "gzip" if is_gzip else "uncompressed"
        raise MergeError(
            f"{path}: compression {compression} does not match the {found} contents",
            EXIT_SOURCE,
        )


def _format_of(path: str, compression: str) -> str:
    """The format named by the extension, or sniffed when the extension is not one."""
    name = Path(path).name
    base = name[: -len(".gz")] if name.endswith(".gz") else name
    named = _FORMAT_BY_SUFFIX.get(Path(base).suffix.lower())
    if named:
        return named
    with open_binary(InputFile(path, "", compression)) as handle:
        if handle.read(len(_PARQUET_MAGIC)) == _PARQUET_MAGIC:
            return "parquet"
    raise MergeError(f"{path}: cannot determine the input format", EXIT_USAGE)

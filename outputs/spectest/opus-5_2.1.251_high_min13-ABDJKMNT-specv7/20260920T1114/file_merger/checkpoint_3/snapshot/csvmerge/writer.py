"""Writing the merged result: one CSV, or a directory of partitioned part files.

Both destinations are published atomically — a temporary file or a sibling
temporary directory is filled first and moved into place only once the whole
result is on disk, so a failed run leaves nothing partly written behind.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Iterable, Iterator, TextIO

from csvmerge.dialect import CsvDialect
from csvmerge.errors import EXIT_ERROR, MergeError

STDOUT = "-"


def write_output(
    destination: str, dialect: CsvDialect, header: list[str], rows: Iterable[list[str]]
) -> None:
    """Write the header and rows as one CSV, quoting as the dialect asks."""
    with _open_destination(destination) as handle:
        handle.write(dialect.format_row(header))
        for cells in rows:
            handle.write(dialect.format_row(cells))


@contextmanager
def staged_directory(destination: str) -> Iterator[Path]:
    """Yield a sibling temporary directory that becomes `destination` on success.

    The staging directory is removed with everything in it if the body raises,
    which covers both a write that fails and a run that stops earlier
    (ambiguity T39 covers publishing into a directory that already exists).
    """
    target = Path(destination)
    if target.exists() and not target.is_dir():
        raise MergeError(
            f"--output {destination} must be a directory when partitioning", EXIT_ERROR
        )
    staging = Path(_make_staging(target))
    try:
        yield staging
        _publish(staging, target)
    except BaseException:
        rmtree(staging, ignore_errors=True)
        raise


def _make_staging(target: Path) -> str:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        return mkdtemp(dir=target.parent, prefix=f".{target.name}-", suffix=".tmp")
    except OSError as error:
        raise MergeError(f"cannot write output {target}: {error}", EXIT_ERROR) from error


def _publish(staging: Path, target: Path) -> None:
    """Move the finished tree into place, merging into a directory already there."""
    try:
        if target.exists():
            _merge_into(staging, target)
        else:
            os.replace(staging, target)
    except OSError as error:
        raise MergeError(f"cannot write output {target}: {error}", EXIT_ERROR) from error


def _merge_into(source: Path, destination: Path) -> None:
    """Move every entry of `source` into the existing directory `destination`."""
    for entry in source.iterdir():
        moved = destination / entry.name
        if entry.is_dir() and moved.is_dir():
            _merge_into(entry, moved)
        else:
            os.replace(entry, moved)
    source.rmdir()


@contextmanager
def _open_destination(destination: str) -> Iterator[TextIO]:
    """Yield the stream to write to; a file appears only once it is complete."""
    if destination == STDOUT:
        yield sys.stdout
        return
    target = Path(destination)
    try:
        scratch = NamedTemporaryFile(
            "w",
            dir=target.parent,
            prefix=f".{target.name}-",
            delete=False,
            newline="",
            encoding="utf-8",
        )
    except OSError as error:
        raise MergeError(
            f"cannot write output {destination}: {error}", EXIT_ERROR
        ) from error
    try:
        with scratch as handle:
            yield handle
        os.replace(scratch.name, target)
    except BaseException:
        os.unlink(scratch.name)
        raise

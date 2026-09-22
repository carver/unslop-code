"""Writing the merged output: to stdout, or atomically onto a file or directory."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import MergeError

#: `mkdtemp` makes a private directory; a published output tree is a normal one.
_OUTPUT_DIR_MODE = 0o755


@contextmanager
def open_output(destination):
    """Yield a text stream for `destination`, or stdout when it is ``-``.

    A file target is written through a temporary file in the same directory and then
    renamed over the destination, so concurrent readers see either the previous file
    or the complete new one, and a failed run leaves neither behind (AMBIGUITIES T29).
    """
    if destination == "-":
        yield sys.stdout
        return

    target = Path(destination)
    handle = _temporary_beside(target)
    try:
        with handle:
            yield handle
    except BaseException:
        os.unlink(handle.name)
        raise
    os.replace(handle.name, target)


def check_directory_target(destination):
    """Reject the `--output` values a partitioned run cannot write into."""
    if destination == "-":
        raise MergeError("--output must be a directory when partitioning, not '-'")
    target = Path(destination)
    if target.exists() and not target.is_dir():
        raise MergeError(f"--output {target} exists and is not a directory")


@contextmanager
def open_output_dir(destination):
    """Yield a staging directory that is renamed onto `destination` on success.

    The staging directory is a sibling of the destination, so the rename is atomic
    and readers never see a half-written tree; a failed run removes the staging
    directory instead, leaving no partial output behind (AMBIGUITIES T34).
    """
    target = Path(destination)
    staging = _staging_beside(target)
    try:
        yield staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _promote(staging, target)


def write_rows(stream, header, rows, dialect):
    """Write the header and rows using the configured CSV dialect."""
    writer = dialect.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)


def _staging_beside(target):
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}.", suffix=".part"))
        staging.chmod(_OUTPUT_DIR_MODE)
        return staging
    except OSError as error:
        raise MergeError(f"cannot write output {target}: {error}") from error


def _promote(staging, target):
    """Move the staging directory onto `target`, discarding what was there before."""
    if not target.exists():
        os.rename(staging, target)
        return
    retired = staging.with_suffix(".old")
    os.rename(target, retired)
    os.rename(staging, target)
    shutil.rmtree(retired)


def _temporary_beside(target):
    try:
        return tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".part",
            delete=False,
        )
    except OSError as error:
        raise MergeError(f"cannot write output {target}: {error}") from error

"""Writing results in the deterministic output dialect.

Both destinations share one dialect: the single CSV of an unpartitioned run,
and the part files of a partitioned one. A file or directory destination is
built beside its final name and moved into place only once the whole result
exists, so a failed run leaves nothing half written.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

#: Directories moved into place get the usual readable mode rather than the
#: private mode mkdtemp creates them with.
_DIRECTORY_MODE = 0o755


def _dialect(fmt) -> dict:
    """The csv module's settings for the output: commas and ``\\n`` endings."""
    return {
        "delimiter": ",",
        "quotechar": fmt.quotechar,
        "doublequote": True,
        "escapechar": fmt.escapechar,
        "quoting": csv.QUOTE_MINIMAL,
        "lineterminator": "\n",
    }


@contextmanager
def open_output(path: str):
    """Yield the destination handle for a single-file result; ``-`` means stdout."""
    if path == "-":
        yield sys.stdout
        return

    target = Path(path)
    scratch = tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False
    )
    try:
        with scratch as handle:
            yield handle
    except BaseException:
        os.unlink(scratch.name)
        raise
    os.replace(scratch.name, target)


@contextmanager
def open_output_directory(path: str):
    """Yield a temporary directory that becomes ``path`` once the run succeeds.

    The temporary directory is a sibling of the destination, so the final move
    is a rename within one filesystem. Anything already at the destination is
    replaced by the completed tree (AMBIGUITIES T38).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}."))
    try:
        yield scratch
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    scratch.chmod(_DIRECTORY_MODE)
    _clear(target)
    scratch.rename(target)


def _clear(target: Path) -> None:
    """Remove whatever occupies the destination path, if anything does."""
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def write_csv(handle, header, rows, fmt) -> None:
    """Write the header and rows of a single-file result."""
    writer = csv.writer(handle, **_dialect(fmt))
    writer.writerow(header)
    writer.writerows(rows)


class RowFormatter:
    """Renders rows one at a time into the exact text a part file receives.

    Part files are cut on byte counts, so the writer needs each row's finished
    text - line ending included - before deciding which file it goes in.
    """

    def __init__(self, fmt):
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer, **_dialect(fmt))

    def text(self, row) -> str:
        self._buffer.seek(0)
        self._buffer.truncate()
        self._writer.writerow(row)
        return self._buffer.getvalue()

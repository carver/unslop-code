"""Choosing and reading the bytes that hold the document to query."""

import sys
from pathlib import Path

from .errors import XjqError


def read_source(infile: str | None) -> bytes:
    """Return the document bytes, from ``infile`` when given and stdin otherwise.

    A named file takes precedence, so stdin is left unread. Raises
    :class:`XjqError` when the file is missing, unreadable, or not UTF-8 text.
    """
    if infile is None:
        return sys.stdin.buffer.read()
    return _read_file(infile)


def _read_file(path: str) -> bytes:
    """Read ``path`` as UTF-8 text, tolerating a leading byte-order mark.

    The text is handed back as UTF-8 bytes, without the mark, so that the
    parsers see exactly what they see for stdin.
    """
    try:
        return Path(path).read_text(encoding="utf-8-sig").encode("utf-8")
    except OSError as error:
        raise XjqError(f"could not read file {path!r}: {error.strerror}") from error
    except UnicodeDecodeError as error:
        raise XjqError(f"could not read file {path!r}: not valid utf-8") from error

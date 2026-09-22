"""Reading the raw document bytes from a file or from stdin."""

import sys
from pathlib import Path

from .errors import XjqError


def read_input(path: str | None) -> bytes:
    """Return the document bytes, read from ``path`` or from stdin when it is ``None``.

    A file is decoded as UTF-8 text, with an optional byte order mark, and
    handed back as UTF-8 bytes so that the parsers see the same input as they do
    for stdin.

    Raises:
        XjqError: the file is missing, unreadable, or not UTF-8 text.
    """
    if path is None:
        return sys.stdin.buffer.read()
    try:
        return Path(path).read_text(encoding="utf-8-sig").encode()
    except OSError as exc:
        raise XjqError(f"error: could not read file {path!r}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise XjqError(f"error: could not read file {path!r}: not utf-8 text") from exc

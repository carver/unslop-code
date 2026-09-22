"""Selection of the document that the query runs against."""

import sys
from pathlib import Path

from errors import InputError


def read_input(path) -> bytes:
    """Return the document bytes named by ``path``, or those on stdin if it is ``None``.

    A file is decoded as UTF-8, with an optional byte order mark, and handed
    back as UTF-8 bytes so that every input reaches the parsers the same way.

    Raises:
        InputError: if ``path`` cannot be read or is not UTF-8 text.
    """
    if path is None:
        return sys.stdin.buffer.read()
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"input error: cannot read {path}: {exc}") from exc
    return text.encode("utf-8")

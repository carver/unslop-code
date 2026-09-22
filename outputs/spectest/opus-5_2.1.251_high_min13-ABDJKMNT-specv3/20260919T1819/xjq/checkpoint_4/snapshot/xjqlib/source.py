"""Reading the document bytes from INFILE or, in its absence, from stdin."""

import sys
from pathlib import Path


class SourceError(Exception):
    """Raised when INFILE cannot be read as UTF-8 text."""


def read_source(path: str | None) -> bytes:
    """Return the bytes of the document to query.

    INFILE wins over stdin whenever it is given. Its bytes are UTF-8 text, so
    they are decoded -- which drops a leading BOM and rejects anything that is
    not UTF-8 -- and handed on re-encoded, since detection and parsing both
    work on bytes. Stdin is passed through untouched, leaving its encoding to
    the XML parser.
    """
    if path is None:
        return sys.stdin.buffer.read()
    try:
        return Path(path).read_bytes().decode("utf-8-sig").encode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceError(f"{path}: {exc}") from exc

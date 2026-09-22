"""Choosing and reading the byte stream the document is parsed from.

`INFILE`, when the command line names one, wins over stdin; otherwise stdin is
read. A file is decoded as UTF-8 text with an optional byte-order mark, then
handed on as UTF-8 bytes so that the parsing stage sees the same shape of input
from either source.
"""

from pathlib import Path

from .errors import FileInputError


def read_document(path, stream):
    """Return the document bytes, from `path` when given and `stream` if not.

    Raises `FileInputError` when `path` cannot be opened or does not hold
    UTF-8 text; the BOM `utf-8-sig` strips is not part of the document.
    """
    if path is None:
        return stream.read()

    try:
        return Path(path).read_bytes().decode("utf-8-sig").encode()
    except (OSError, UnicodeDecodeError) as exc:
        raise FileInputError(path, exc) from exc

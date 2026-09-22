"""Reading of the document to query from a file or from standard input."""

import sys


class InputReadError(Exception):
    """The file named on the command line cannot be read as UTF-8 text."""


def read_document(path):
    """Return the bytes of the document to query.

    `path` names the file to read and takes precedence over stdin, which is
    read instead when it is None. A file is decoded as UTF-8 text and
    re-encoded, which drops the byte order mark it is allowed to start with;
    stdin is passed on as it arrives, leaving any encoding declaration it
    carries to the XML parser.
    """
    if path is None:
        return sys.stdin.buffer.read()
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return handle.read().encode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputReadError(exc) from exc

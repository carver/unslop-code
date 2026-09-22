"""Reading the bytes of the document to query.

The document comes from `INFILE` when one is given and from stdin otherwise.
File input is defined as UTF-8 text, so it is decoded here; stdin is passed on
untouched, letting an XML declaration pick the encoding.
"""

import sys
from pathlib import Path

from .errors import InputReadError


def read_source(path: str | None) -> bytes:
    """Return the document bytes from `path`, or from stdin when it is `None`."""
    if path is None:
        return sys.stdin.buffer.read()
    return read_file(path)


def read_file(path: str) -> bytes:
    """Read `path` as UTF-8 text and return the bytes the parsers work on.

    Decoding with `utf-8-sig` both rejects input that is not UTF-8 and drops a
    leading BOM; re-encoding keeps the pipeline on bytes, so a file whose XML
    declaration names an encoding still parses.
    """
    try:
        return Path(path).read_bytes().decode("utf-8-sig").encode("utf-8")
    except OSError as exc:
        raise InputReadError(f"failed to read {path}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise InputReadError(f"failed to decode {path} as utf-8: {exc}") from exc

"""Naming rules for Hive-style partition directories.

A partition value becomes one path segment ``<path>=<value>``: the value is
the one the schema cast produced, rendered like the cell it will also appear
as, then percent-encoded so that the segment is a single, portable path
component. Missing values get the literal ``_null``.
"""

from __future__ import annotations

import string
from pathlib import Path

from .casting import render_value

#: The characters a segment may carry as themselves; everything else, ``/`` and
#: space included, is percent-encoded byte by byte.
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "._-")

NULL_SEGMENT = "_null"


def encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes of characters outside ``[A-Za-z0-9._-]``."""
    return "".join(char if char in _UNRESERVED else _percent(char) for char in text)


def _percent(char: str) -> str:
    return "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))


def segment_of(value, spec) -> str:
    """The encoded segment one partition cell contributes.

    Nulls - absent, empty or coerced - share the ``_null`` segment; see
    AMBIGUITIES T41.
    """
    return NULL_SEGMENT if value is None else encode(render_value(value, spec))


def directory(root: Path, columns, segments) -> Path:
    """The partition directory under ``root`` for one row's segments."""
    return root.joinpath(*(f"{column}={segment}" for column, segment in zip(columns, segments)))

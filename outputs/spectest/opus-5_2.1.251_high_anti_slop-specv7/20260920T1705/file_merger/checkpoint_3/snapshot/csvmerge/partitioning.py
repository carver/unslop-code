"""Hive-style naming of the directory a row belongs in.

A partitioned run derives one path segment per ``--partition-by`` column,
``<col>=<val>``, from the row's cast values.  Values are percent-encoded so
that every byte outside ``[A-Za-z0-9._-]`` survives a round trip through a file
name — a space becomes ``%20`` and a separator ``%2F`` — and a row with no
value for a partition column lands under the literal ``_null``.
"""

from __future__ import annotations

import string
from typing import Sequence

#: Segment used for rows whose partition value is null or absent.
NULL_SEGMENT = "_null"

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "._-")


def encode_value(value: str) -> str:
    """Percent-encode the UTF-8 bytes of a partition value."""
    return "".join(
        chr(byte) if chr(byte) in _UNRESERVED else f"%{byte:02X}"
        for byte in value.encode("utf-8")
    )


def segments(names: Sequence[str], values: Sequence[str | None]) -> tuple[str, ...]:
    """Build the ``<col>=<val>`` path segments of one row, in column order."""
    return tuple(
        f"{name}={NULL_SEGMENT if value is None else encode_value(value)}"
        for name, value in zip(names, values)
    )

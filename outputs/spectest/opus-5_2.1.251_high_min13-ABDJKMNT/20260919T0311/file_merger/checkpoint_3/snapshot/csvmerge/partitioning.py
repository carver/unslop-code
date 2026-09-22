"""Hive-style partition directories: how a row's values name its location."""
from __future__ import annotations

from typing import Sequence

#: Characters a path segment carries as themselves. Everything else is
#: percent-encoded, so no value can introduce a path separator of its own.
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)

#: The segment value standing in for a null or missing partition value.
NULL_SEGMENT = "_null"


def encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes of every character outside the unreserved set."""
    return "".join(
        character if character in _UNRESERVED
        else "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))
        for character in text
    )


def hive_path(columns: Sequence[str], values: Sequence[str | None]) -> str:
    """The `col=val/...` directory for one row; a `None` value becomes `_null`.

    With no partition columns the path is empty, which is the output root: an
    unpartitioned run is simply the single-partition case.
    """
    return "/".join(
        f"{encode(column)}={NULL_SEGMENT if value is None else encode(value)}"
        for column, value in zip(columns, values)
    )

"""Naming the Hive-style directory a row belongs in.

A partitioned row lands under ``<path>=<value>`` segments, one per
``--partition-by`` field path and in the order they were given. Values are the
ones cast to the resolved schema, rendered the same way the CSV cells are, so
a partition directory and the value it came from always agree - and the
segment names the whole path, so ``attrs["country"]`` and ``user.country``
cannot be mistaken for each other.
"""

from __future__ import annotations

import string
from typing import Any, Sequence

from csvmerge.paths import FieldPath
from csvmerge.values import format_value

# The segment a missing partition value gets; it cannot collide with an
# encoded real value, which never yields a leading underscore.
NULL_SEGMENT = "_null"

_SAFE_CHARACTERS = frozenset(string.ascii_letters + string.digits + "._-")


def partition_path(paths: Sequence[FieldPath], values: Sequence[Any]) -> str:
    """Build the relative directory for one row, empty when nothing partitions it."""
    return "/".join(f"{encode(path.text)}={_segment(path.read(values))}" for path in paths)


def encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes of everything outside ``[A-Za-z0-9._-]``."""
    return "".join(character if character in _SAFE_CHARACTERS else _escape(character) for character in text)


def _escape(character: str) -> str:
    return "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))


def _segment(value: Any) -> str:
    return NULL_SEGMENT if value is None else encode(format_value(value, ""))

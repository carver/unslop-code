"""Hive-style partition directories: the segments a row's values name.

A partition is addressed by one ``<column>=<value>`` directory segment per
``--partition-by`` column, in the order the flag lists them. Values are the
cells the row would show in the output CSV, percent-encoded so that a segment is
always a single, safe path component.
"""

from __future__ import annotations

NULL_SEGMENT = "_null"

_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)


def encode_value(value: str) -> str:
    """Percent-encode the UTF-8 bytes of everything outside [A-Za-z0-9._-]."""
    return "".join(
        character if character in _UNRESERVED else _percent_encode(character)
        for character in value
    )


def segments(names: list[str], values: list[str | None]) -> tuple[str, ...]:
    """The directory segments for one row; a null value becomes ``_null``."""
    return tuple(
        f"{name}={NULL_SEGMENT if value is None else encode_value(value)}"
        for name, value in zip(names, values)
    )


def _percent_encode(character: str) -> str:
    return "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))

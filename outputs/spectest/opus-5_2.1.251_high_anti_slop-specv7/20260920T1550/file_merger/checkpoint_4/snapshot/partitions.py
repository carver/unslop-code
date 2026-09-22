"""Hive-style partition segments for the output directory tree.

A row's partition is one ``<path>=<value>`` directory name per
``--partition-by`` field path, in the order the paths were given.  Names and
values are percent-encoded so that every segment is a single, safe path
component, and a row that has no value for a partition column lands in
``<column>=_null``.
"""

from __future__ import annotations

import string

from errors import UsageError
from field_paths import FieldPath, resolve_paths
from schema import Column, declared_types

# The value segment a row with no value for the column is written under.
NULL_SEGMENT = "_null"

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "._-")

# Percent-encoding of every byte, so encoding is a lookup per UTF-8 byte.
_ENCODED = [chr(byte) if chr(byte) in _UNRESERVED else f"%{byte:02X}" for byte in range(256)]


def encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes outside ``[A-Za-z0-9._-]``."""
    return "".join(_ENCODED[byte] for byte in text.encode("utf-8"))


def segment(name: str, value: str | None) -> str:
    """One directory name of a partition; ``None`` is a missing value."""
    return f"{encode(name)}={NULL_SEGMENT if value is None else encode(value)}"


def resolve_partition_paths(columns: list[Column], requested: str | None) -> list[FieldPath]:
    """Split ``--partition-by`` and resolve every field path against the schema."""
    if requested is None:
        return []
    names = [name.strip() for name in requested.split(",") if name.strip()]
    if not names:
        raise UsageError("--partition-by needs at least one column name")
    return resolve_paths(names, declared_types(columns), "partition column", UsageError)

"""Hive-style partition segments for the output directory tree.

A row's partition is one ``<column>=<value>`` directory name per
``--partition-by`` column, in the order the columns were given.  Names and
values are percent-encoded so that every segment is a single, safe path
component, and a row that has no value for a partition column lands in
``<column>=_null``.
"""

from __future__ import annotations

import string

from errors import UsageError
from schema import Column

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


def resolve_partition_columns(columns: list[Column], requested: str | None) -> list[str]:
    """Split ``--partition-by`` and check every name against the schema."""
    if requested is None:
        return []
    names = [name.strip() for name in requested.split(",") if name.strip()]
    if not names:
        raise UsageError("--partition-by needs at least one column name")
    known = {column.name for column in columns}
    missing = [name for name in names if name not in known]
    if missing:
        raise UsageError(
            f"partition column(s) not in the resolved schema: {', '.join(missing)}"
        )
    return names

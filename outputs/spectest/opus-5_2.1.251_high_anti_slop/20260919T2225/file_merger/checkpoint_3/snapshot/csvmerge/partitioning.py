"""Hive-style partition segments: which columns split the output, and how they are spelled."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from string import ascii_letters, digits

from .casting import Cell, format_cell
from .schema import Column, Schema

#: Segment text used when a partition column has no value.
NULL_SEGMENT = "_null"

#: Characters a segment carries literally; every other one is percent-encoded.
_UNRESERVED = frozenset(ascii_letters + digits + "._-")


@dataclass(frozen=True)
class PartitionScheme:
    """The schema columns whose values split the output into directories.

    Empty when ``--partition-by`` was not given, which makes :meth:`segments`
    return no path components and leaves every row in the output root.
    """

    columns: tuple[tuple[int, Column], ...]

    @classmethod
    def resolve(cls, schema: Schema, names: Sequence[str]) -> PartitionScheme:
        """Locate ``names`` in the resolved schema, keeping the order given."""
        indexes = [schema.index_of(name) for name in names]
        return cls(tuple((index, schema.columns[index]) for index in indexes))

    def segments(self, cells: Sequence[Cell]) -> list[str]:
        """Return the ``col=value`` path components for one row's cast cells."""
        return [
            f"{encode(column.name)}={encode(format_cell(cells[index], column, NULL_SEGMENT))}"
            for index, column in self.columns
        ]


def encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes of every character outside ``[A-Za-z0-9._-]``."""
    return "".join(character if character in _UNRESERVED else _percent(character) for character in text)


def _percent(character: str) -> str:
    return "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))

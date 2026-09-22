"""Hive-style partition segments: which columns split the output, and how they are spelled."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from string import ascii_letters, digits

from .casting import format_cell
from .nested import Node
from .paths import FieldPath, ResolvedPath, resolve as resolve_path
from .schema import Schema

#: Segment text used when a partition column has no value.
NULL_SEGMENT = "_null"

#: Characters a segment carries literally; every other one is percent-encoded.
_UNRESERVED = frozenset(ascii_letters + digits + "._-")


@dataclass(frozen=True)
class PartitionScheme:
    """The field paths whose values split the output into directories.

    Empty when ``--partition-by`` was not given, which makes :meth:`segments`
    return no path components and leaves every row in the output root. A path
    into a nested column is spelled with dots — ``attrs["country"]`` names the
    directories ``attrs.country=...`` — and has to end on a primitive.
    """

    paths: tuple[ResolvedPath, ...]

    @classmethod
    def resolve(cls, schema: Schema, paths: Sequence[FieldPath]) -> PartitionScheme:
        """Match ``paths`` against the resolved schema, keeping the order given."""
        return cls(tuple(resolve_path(schema, path, "partition") for path in paths))

    def segments(self, columns: Sequence[Node]) -> list[str]:
        """Return the ``path=value`` directory components for one row's cast columns."""
        return [
            f"{encode(path.path.label)}={encode(format_cell(path.extract(columns), NULL_SEGMENT))}"
            for path in self.paths
        ]


def encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes of every character outside ``[A-Za-z0-9._-]``."""
    return "".join(character if character in _UNRESERVED else _percent(character) for character in text)


def _percent(character: str) -> str:
    return "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))

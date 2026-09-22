"""Hive-style partition directory names.

A partitioned run derives one relative directory per row — `country=US/dt=2024-01-01`
— from the row's values *after* they have been cast to the resolved schema types, so
the segment text is exactly the text the same value would have in a CSV cell. A
partition field path names its directory in full, encoded (AMBIGUITIES T62).
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from .coltypes import render
from .paths import PARTITION, resolve_all

#: Segment text standing in for a partition column with no value.
NULL_SEGMENT = "_null"

#: The characters a segment may contain literally; everything else is encoded.
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "._-")


def encode_segment(text):
    """Percent-encode the UTF-8 bytes of every character outside `[A-Za-z0-9._-]`."""
    return "".join(
        character if character in _UNRESERVED else _percent(character) for character in text
    )


def _percent(character):
    return "".join(f"%{byte:02X}" for byte in character.encode("utf-8"))


@dataclass(frozen=True)
class PartitionSpec:
    """The `--partition-by` field paths, resolved against the output schema."""

    paths: tuple

    @classmethod
    def build(cls, schema, spec):
        """Resolve a comma-separated `--partition-by` value against `schema`."""
        return cls(resolve_all(schema, spec, PARTITION))

    def directory(self, values):
        """The relative directory holding the rows whose cast `values` these are."""
        return "/".join(
            f"{encode_segment(path.text)}={_segment(path.extract(values))}" for path in self.paths
        )


def _segment(value):
    """Render one cast partition value as its directory segment."""
    return NULL_SEGMENT if value is None else encode_segment(render(value, ""))

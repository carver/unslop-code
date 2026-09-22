"""Field paths: how ``--key`` and ``--partition-by`` name a value in a row.

A path starts at a column and walks into whatever the schema declares it to
be: ``.name`` picks a struct field, ``.0`` an array element and ``["country"]``
a map entry, so ``user.id``, ``items.0.qty`` and ``attrs["country"]`` are all
one value of one row.  A path that does not end on a primitive cannot be sorted
or partitioned on and is rejected when the schema is resolved; a path that ends
on a value the row happens not to carry simply reads as null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from casting import ValueType
from column_types import ColumnType
from errors import KeyColumnError, MergeError
from nested_types import ArrayType, MapType, StructType

# One segment after the root column: ``.name``, ``.0`` or ``["key"]``.  The
# quotes around a map key are required, which is what keeps a key of "0"
# distinct from an array index.
_SEGMENT = re.compile(r'\.(?P<member>[^.\[\]"]+)|\["(?P<key>(?:[^"\\]|\\.)*)"\]')
_INDEX = re.compile(r"[0-9]+\Z")
_ESCAPE = re.compile(r"\\(.)")


class Segment(Protocol):
    """One step of a path: what it means in the schema, and in a row."""

    def child_type(self, parent: ValueType) -> ValueType | None:
        """The declared type this step leads to, or ``None`` if it leads nowhere."""

    def read(self, value: object) -> object:
        """The value this step leads to, or ``None`` if the row has none."""


@dataclass(frozen=True)
class Field:
    """A struct field, written ``.name``."""

    name: str

    def child_type(self, parent: ValueType) -> ValueType | None:
        return parent.field_type(self.name) if isinstance(parent, StructType) else None

    def read(self, value: object) -> object:
        return value.get(self.name) if isinstance(value, dict) else None


@dataclass(frozen=True)
class Index:
    """An array element, written ``.0``; indices are non-negative integers."""

    position: int

    def child_type(self, parent: ValueType) -> ValueType | None:
        return parent.element if isinstance(parent, ArrayType) else None

    def read(self, value: object) -> object:
        if isinstance(value, list) and self.position < len(value):
            return value[self.position]
        return None


@dataclass(frozen=True)
class Key:
    """A map entry, written ``["key"]``; the key is matched exactly."""

    name: str

    def child_type(self, parent: ValueType) -> ValueType | None:
        return parent.value if isinstance(parent, MapType) else None

    def read(self, value: object) -> object:
        return value.get(self.name) if isinstance(value, dict) else None


@dataclass(frozen=True)
class ParsedPath:
    """A path split into the column it starts at and the steps from there."""

    text: str
    column: str
    segments: tuple[Segment, ...]

    def resolve(self, declared: ValueType, noun: str) -> "FieldPath":
        """Walk the schema along this path; it has to end on a primitive.

        A step the schema does not allow leads nowhere, and so does a path that
        stops on a struct, an array or a map: neither can be sorted on.
        """
        for segment in self.segments:
            declared = segment.child_type(declared) if declared is not None else None
        if not isinstance(declared, ColumnType):
            raise KeyColumnError(f'{noun} "{self.text}" does not resolve to a primitive')
        return FieldPath(self.text, self.column, self.segments, declared)


@dataclass(frozen=True)
class FieldPath:
    """A parsed path and the primitive type the schema says it ends on."""

    text: str
    column: str
    segments: tuple[Segment, ...]
    type: ColumnType

    def read(self, values: dict[str, object]) -> object:
        """The value this path names in a row of cast values, or ``None``."""
        value = values.get(self.column)
        for segment in self.segments:
            if value is None:
                return None
            value = segment.read(value)
        return value


def parse(text: str) -> ParsedPath:
    """Split ``user.id``, ``items.0.qty`` or ``attrs["country"]`` into its steps."""
    root = re.split(r"[.\[]", text, maxsplit=1)[0]
    if not root:
        raise KeyColumnError(f'field path "{text}" does not start with a column')
    segments, position = [], len(root)
    while position < len(text):
        match = _SEGMENT.match(text, position)
        if match is None:
            raise KeyColumnError(f'field path "{text}" is not a valid path')
        segments.append(_segment(match))
        position = match.end()
    return ParsedPath(text, root, tuple(segments))


def _segment(match: re.Match[str]) -> Segment:
    if match["key"] is not None:
        return Key(_ESCAPE.sub(r"\1", match["key"]))
    member = match["member"]
    return Index(int(member)) if _INDEX.match(member) else Field(member)


def resolve_paths(
    names: Sequence[str],
    columns: Mapping[str, ValueType],
    noun: str,
    missing: type[MergeError],
) -> list[FieldPath]:
    """Parse ``names`` as field paths and resolve them against the schema.

    ``noun`` names them in messages, and ``missing`` is raised for the paths
    that do not start at a column of the schema; a path that starts at one but
    does not end on a primitive is a key column error whatever ``noun`` is.
    """
    paths = [parse(name) for name in names]
    unknown = [path.text for path in paths if path.column not in columns]
    if unknown:
        raise missing(f"{noun}(s) not in the resolved schema: {', '.join(unknown)}")
    return [path.resolve(columns[path.column], noun) for path in paths]

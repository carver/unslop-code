"""Field paths: the spellings ``--key`` and ``--partition-by`` accept, and their leaves.

A path starts at a column and descends through the nested types: ``user.id``
walks into a struct, ``items.0.sku`` indexes an array, and ``attrs["country"]``
or the equivalent ``attrs.country`` reads a map key. A path has to end on a
primitive, since that is the only thing that can be sorted or spelled in a
partition directory name.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .casting import NULL_CELL, Cell
from .datatypes import ArrayType, DataType, MapType, StructType, is_primitive
from .errors import SchemaError
from .nested import Node
from .schema import Schema

#: One path segment: a bracketed key, quoted or not, or a plain dotted name.
_SEGMENT = re.compile(
    r"""\[\s*(?:"(?P<quoted>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\]]*?))\s*\]"""
    r"""|(?P<name>[^.\[\]]+)"""
)

#: What one segment of a path lands on: the type there, and the step reaching it.
_Step = tuple[DataType, str | int]


@dataclass(frozen=True)
class FieldPath:
    """A parsed path, before it has been matched against a schema."""

    text: str
    segments: tuple[str, ...]

    @property
    def label(self) -> str:
        """The dotted spelling, used for partition directory names."""
        return ".".join(self.segments)


@dataclass(frozen=True)
class ResolvedPath:
    """A path matched against the schema: which column to start at, and how to descend."""

    path: FieldPath
    column: int
    steps: tuple[str | int, ...]

    def extract(self, columns: Sequence[Node]) -> Cell:
        """Follow the path into one row's cast columns; anything missing is a null."""
        node = columns[self.column]
        for step in self.steps:
            node = _descend(node, step)
        return node


def parse_paths(text: str) -> list[FieldPath]:
    """Parse the comma-separated list of paths one option carries.

    Commas inside a bracketed key belong to the key, not to the list.
    """
    return [parse_path(part) for part in _split(text)]


def parse_path(text: str) -> FieldPath:
    """Parse one path into its segments, rejecting anything the grammar has no room for."""
    stripped = text.strip()
    segments: list[str] = []
    position = 0
    while position < len(stripped):
        if segments:
            if stripped[position] not in ".[":
                raise ValueError(f"expected '.' or '[' in the field path {text!r} at offset {position}")
            position += stripped[position] == "."
        match = _SEGMENT.match(stripped, position)
        if match is None:
            raise ValueError(f"cannot read the field path {text!r} at offset {position}")
        segments.append(next(group for group in match.groups() if group is not None))
        position = match.end()
    if not segments:
        raise ValueError(f"empty field path in {text!r}")
    return FieldPath(stripped, tuple(segments))


def resolve(schema: Schema, path: FieldPath, role: str) -> ResolvedPath:
    """Match a path against the schema, reporting where it stops resolving.

    ``role`` is the word the error message calls the path: ``key`` or
    ``partition``.
    """
    column = schema.index_of(path.segments[0])
    data_type = schema.columns[column].type
    steps: list[str | int] = []
    for segment in path.segments[1:]:
        data_type, step = _step(data_type, segment, path, role)
        steps.append(step)
    if not is_primitive(data_type):
        raise SchemaError(f'{role} column "{path.text}" does not resolve to a primitive')
    return ResolvedPath(path, column, tuple(steps))


def _split(text: str) -> Iterator[str]:
    """Split on the commas that are not inside a ``[...]`` key."""
    depth = 0
    start = 0
    for position, character in enumerate(text):
        depth += (character == "[") - (character == "]")
        if character == "," and depth == 0:
            yield text[start:position]
            start = position + 1
    yield text[start:]


def _descend(node: Node, step: str | int) -> Node:
    if isinstance(step, int):
        return node[step] if isinstance(node, list) and step < len(node) else NULL_CELL
    return node.get(step, NULL_CELL) if isinstance(node, dict) else NULL_CELL


def _into_struct(data_type: StructType, segment: str, path: FieldPath, role: str) -> _Step:
    field = next((field for field in data_type.fields if field.name == segment), None)
    if field is None:
        raise SchemaError(f'{role} column "{path.text}": the struct has no field {segment!r}')
    return field.type, segment


def _into_array(data_type: ArrayType, segment: str, path: FieldPath, role: str) -> _Step:
    if not segment.isdecimal():
        raise SchemaError(f'{role} column "{path.text}": {segment!r} is not an array index')
    return data_type.element, int(segment)


def _into_map(data_type: MapType, segment: str, _path: FieldPath, _role: str) -> _Step:
    return data_type.value, segment


_STEPS = {StructType: _into_struct, ArrayType: _into_array, MapType: _into_map}


def _step(data_type: DataType, segment: str, path: FieldPath, role: str) -> _Step:
    """Take one segment of the path into ``data_type``, returning what it lands on."""
    into = _STEPS.get(type(data_type))
    if into is None:
        raise SchemaError(f'{role} column "{path.text}" does not resolve to a primitive')
    return into(data_type, segment, path, role)

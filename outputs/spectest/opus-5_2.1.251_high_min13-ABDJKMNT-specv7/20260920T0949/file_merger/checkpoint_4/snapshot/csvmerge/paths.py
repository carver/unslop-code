"""Field paths: how ``--key`` and ``--partition-by`` reach into nested values.

A path starts at a column and then traverses structs by name (``user.id``),
arrays by index (``items.0.sku``) and maps by a bracketed, double-quoted key
(``attrs["country"]``). Resolving a path against the schema yields a
:class:`FieldRef`: where the column sits, the steps down to the leaf, and the
primitive type the leaf must have.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import NamedTuple

from .casting import TypeSpec
from .datatypes import Array, Mapping, Primitive, Struct
from .errors import KeyColumnError, UsageError
from .schema import Schema

#: One step of a path as written: a dotted name, or a bracketed quoted key.
_SEGMENT_RE = re.compile(r'\.([^.\[\]]+)|\[("(?:[^"\\]|\\.)*")\]')
_HEAD_RE = re.compile(r"[^.\[\]]*")


class Segment(NamedTuple):
    """One segment as it was written: its text, and whether it was bracketed."""

    text: str
    bracketed: bool


class Member(NamedTuple):
    """A struct field or a map key: a lookup by name in a JSON object."""

    name: str


class Index(NamedTuple):
    """A position in an array."""

    position: int


@dataclass(frozen=True)
class FieldRef:
    """A resolved path: the column it starts at and the leaf it ends on."""

    path: str
    column: int
    steps: tuple[Member | Index, ...]
    spec: TypeSpec


def split_paths(text: str) -> list[str]:
    """Split a comma separated path list, keeping commas inside quoted keys."""
    paths, start, quoted = [], 0, False
    for position, char in enumerate(text):
        quoted ^= char == '"'
        if char == "," and not quoted:
            paths.append(text[start:position])
            start = position + 1
    return paths + [text[start:]]


def resolve_field(schema: Schema, path: str, role: str = "key") -> FieldRef:
    """Resolve one path against the schema, or say why it does not resolve.

    A path that is itself a column name is taken as that column, so a flat
    column whose name contains a dot stays reachable (AMBIGUITIES T63).
    """
    head, segments = (path, ()) if path in schema.names else _parse(path, role)
    column = schema.index_of(head, role)
    datatype = schema.columns[column].type

    steps = []
    for segment in segments:
        step = _step(datatype, segment, path, role)
        datatype = _descend(datatype, step)
        steps.append(step)

    if not isinstance(datatype, Primitive):
        raise KeyColumnError(f'ERR 3 {role} column "{path}" does not resolve to a primitive')
    return FieldRef(path, column, tuple(steps), datatype.spec)


def value_at(value, steps):
    """Follow ``steps`` into a cast value; anything missing makes it null."""
    for step in steps:
        if isinstance(step, Index):
            value = value[step.position] if isinstance(value, list) and step.position < len(value) else None
        else:
            value = value.get(step.name) if isinstance(value, dict) else None
        if value is None:
            return None
    return value


def _parse(path: str, role: str) -> tuple[str, list[Segment]]:
    """Split a path into the column it starts at and the segments after it."""
    head = _HEAD_RE.match(path).group()
    if not head:
        raise UsageError(f'{role} path "{path}" does not start with a column name')

    segments, position = [], len(head)
    while position < len(path):
        match = _SEGMENT_RE.match(path, position)
        if match is None:
            raise UsageError(f'{role} path "{path}" is malformed at offset {position}')
        dotted, quoted = match.groups()
        segments.append(Segment(dotted, False) if dotted is not None else Segment(json.loads(quoted), True))
        position = match.end()
    return head, segments


def _step(datatype, segment: Segment, path: str, role: str):
    """Turn one written segment into the step its target type calls for."""
    if isinstance(datatype, Mapping) and segment.bracketed:
        return Member(segment.text)
    if isinstance(datatype, Array) and not segment.bracketed and segment.text.isdecimal():
        return Index(int(segment.text))
    if isinstance(datatype, Struct) and datatype.field(segment.text) is not None:
        return Member(segment.text)
    raise KeyColumnError(f'ERR 3 {role} column "{path}" does not resolve to a primitive')


def _descend(datatype, step):
    """The declared type a step arrives at."""
    if isinstance(datatype, Array):
        return datatype.element
    if isinstance(datatype, Mapping):
        return datatype.value
    return datatype.field(step.name)

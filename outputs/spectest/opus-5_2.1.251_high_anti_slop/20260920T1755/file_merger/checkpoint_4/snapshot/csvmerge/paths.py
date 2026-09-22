"""Field paths: naming a value inside a nested column.

``--key`` and ``--partition-by`` take paths rather than plain column names, so
``user.id`` reaches a struct field, ``items.0.qty`` an array element, and
``attrs["country"]`` a map entry. A path is checked against the schema once,
before any row is read: it has to end on a primitive type, and every step has
to exist in the type it steps into. What it resolves to is then read out of
each cast row, where a missing entry, an index past the end of an array and a
null along the way all read as null.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.types import Array, DataType, Map, Primitive, Struct

# A path segment: a bare name, or a bracketed map key. Commas inside brackets
# belong to the key, so they do not separate one path from the next.
_BRACKET = re.compile(r'\[("(?:[^"\\]|\\.)*")\]')
_NAME = re.compile(r"[^.\[\]]+")
_PATH = re.compile(r"(?:\[[^\]]*\]|[^,])+")


@dataclass(frozen=True)
class FieldPath:
    """A path resolved against the schema: which column, and how to walk into it."""

    text: str
    column: int
    steps: tuple[str | int, ...]

    def read(self, values: Sequence[Any]) -> Any:
        """Follow the path into one row's cast values, or return ``None``."""
        current = values[self.column]
        for step in self.steps:
            if isinstance(step, int):
                if not isinstance(current, list) or step >= len(current):
                    return None
                current = current[step]
            elif isinstance(current, dict):
                current = current.get(step)
            else:
                return None
            if current is None:
                return None
        return current


def split_paths(text: str) -> list[str]:
    """Split a comma separated list of paths, leaving bracketed keys whole."""
    return _PATH.findall(text)


def resolve_path(text: str, columns: Sequence, role: str) -> FieldPath:
    """Locate ``text`` in the resolved schema's columns, insisting it names a primitive.

    ``role`` names what the path is for - ``key`` or ``partition`` - and only
    appears in error messages.
    """
    segments = _segments(text, role)
    names = [column.name for column in columns]
    head = segments[0]
    if head.text not in names:
        raise MergeError(
            f"{role} column(s) {head.text} are not in the resolved schema: {', '.join(names)}",
            EXIT_SCHEMA,
        )
    index = names.index(head.text)
    steps, declared = _walk(text, columns[index].type, segments[1:], role)
    if not isinstance(declared, Primitive):
        raise MergeError(
            f"{role} column {text!r} does not resolve to a primitive; it names a {declared}",
            EXIT_SCHEMA,
        )
    return FieldPath(text, index, steps)


@dataclass(frozen=True)
class _Segment:
    """One step of a written path, and whether brackets spelled it."""

    text: str
    bracketed: bool


def _walk(
    text: str, declared: DataType, segments: Sequence[_Segment], role: str
) -> tuple[tuple[str | int, ...], DataType]:
    """Step through the declared types, collecting how to read each step back."""
    steps: list[str | int] = []
    for segment in segments:
        if isinstance(declared, Struct):
            field = next((one for one in declared.fields if one.name == segment.text), None)
            if field is None:
                raise MergeError(
                    f"{role} column {text!r}: {declared} has no field {segment.text!r}", EXIT_SCHEMA
                )
            declared = field.type
            steps.append(segment.text)
        elif isinstance(declared, Array):
            steps.append(_index(text, segment, role))
            declared = declared.element
        elif isinstance(declared, Map):
            steps.append(segment.text)
            declared = declared.value
        else:
            raise MergeError(
                f"{role} column {text!r}: {segment.text!r} steps into a {declared}, "
                "which has no fields",
                EXIT_SCHEMA,
            )
    return tuple(steps), declared


def _index(text: str, segment: _Segment, role: str) -> int:
    """Read an array index, which is a bare non-negative integer."""
    if segment.bracketed or not segment.text.isdecimal():
        raise MergeError(
            f"{role} column {text!r}: {segment.text!r} is not an array index", EXIT_SCHEMA
        )
    return int(segment.text)


def _segments(text: str, role: str) -> list[_Segment]:
    """Split a written path into its steps: ``a.0["k"]`` is three of them."""
    segments: list[_Segment] = []
    position = 0
    while position < len(text):
        if text[position] == "[":
            match = _BRACKET.match(text, position)
            if match is None:
                raise MergeError(f"{role} column {text!r}: unterminated map key", EXIT_SCHEMA)
            segments.append(_Segment(json.loads(match.group(1)), bracketed=True))
        else:
            if segments:
                if text[position] != ".":
                    raise MergeError(
                        f"{role} column {text!r}: expected a '.' at position {position}", EXIT_SCHEMA
                    )
                position += 1
            match = _NAME.match(text, position)
            if match is None:
                raise MergeError(f"{role} column {text!r}: empty path segment", EXIT_SCHEMA)
            segments.append(_Segment(match.group(), bracketed=False))
        position = match.end()
    if not segments:
        raise MergeError(f"{role} column: an empty path names nothing", EXIT_SCHEMA)
    return segments

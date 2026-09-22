"""Field paths: `user.id`, `items.0.sku`, `attrs["country"]`.

A path names a column and then walks into the value it holds. Where the schema
declares the shape, the walk is checked once, before any row is read; inside a
`json` column there is no declared shape, so the path is resolved per row and only
its result is checked (AMBIGUITIES T58).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import KeyPathError, MissingKeyError
from .typespec import AnyJson, Array, Map, Struct

KEY = "key column"
PARTITION = "partition column"

#: One traversal step: a bracketed `["name"]`, or a dotted `.name`.
_STEP = re.compile(r'\["(?P<quoted>[^"]*)"\]|\.(?P<plain>[^.\[\]]+)')


@dataclass(frozen=True)
class Step:
    """One traversal step, as both a mapping key and an array position."""

    key: str
    index: int | None

    def of(self, value):
        """Take this step into `value`, or return None where it cannot be taken."""
        if isinstance(value, list):
            return value[self.index] if self.index is not None and self.index < len(value) else None
        if isinstance(value, dict):
            return value.get(self.key)
        return None


@dataclass(frozen=True)
class FieldPath:
    """A resolved `--key` or `--partition-by` path."""

    text: str
    role: str
    column: int
    steps: tuple[Step, ...]

    def extract(self, values):
        """Read this path out of one row's cast values."""
        value = values[self.column]
        for step in self.steps:
            if value is None:
                return None
            value = step.of(value)
        if isinstance(value, (dict, list)):
            raise KeyPathError(not_primitive(self.text, self.role))
        return value


def not_primitive(text, role):
    """The message a path that lands on a struct, array or map reports."""
    return f'{role} "{text}" does not resolve to a primitive'


def parse_path(schema, text, role):
    """Resolve one path against `schema`, checking it can only yield a primitive."""
    column, remainder = _split_column(schema, text, role)
    steps = _steps(schema.columns[column].type, text, role, remainder)
    return FieldPath(text, role, column, steps)


def _split_column(schema, text, role):
    """Take the longest declared column name the path starts with."""
    names = schema.names
    matches = [
        name
        for name in names
        if text == name or text.startswith(name + ".") or text.startswith(name + "[")
    ]
    if not matches:
        raise MissingKeyError(f'{role} "{text}" is not in the resolved schema')
    name = max(matches, key=len)
    return names.index(name), text[len(name) :]


def _steps(declared, text, role, remainder):
    """Walk the declared types along `remainder`, collecting the runtime steps."""
    steps = []
    for segment in _segments(text, role, remainder):
        declared, step = _step_into(declared, segment, text, role)
        steps.append(step)
    if isinstance(declared, (Struct, Array, Map)):
        raise KeyPathError(not_primitive(text, role))
    return tuple(steps)


def _segments(text, role, remainder):
    """Split the part of a path that follows the column name."""
    position = 0
    while position < len(remainder):
        match = _STEP.match(remainder, position)
        if match is None:
            raise KeyPathError(f'{role} "{text}" is not a valid field path')
        position = match.end()
        yield match["quoted"] if match["quoted"] is not None else match["plain"]


def _step_into(declared, segment, text, role):
    """Take one step through the declared types, returning what it lands on."""
    if isinstance(declared, Struct):
        field = next((one for one in declared.fields if one.name == segment), None)
        if field is None:
            raise MissingKeyError(f'{role} "{text}" has no field {segment!r}')
        return field.type, Step(segment, None)
    if isinstance(declared, Array):
        return declared.element, Step(segment, _index(segment, text, role))
    if isinstance(declared, Map):
        return declared.value, Step(segment, None)
    if isinstance(declared, AnyJson):
        return declared, Step(segment, int(segment) if segment.isdigit() else None)
    raise KeyPathError(f'{role} "{text}" descends into a {declared.label}')


def _index(segment, text, role):
    """Array indices must be non-negative integers (AMBIGUITIES T61)."""
    if not segment.isdigit():
        raise KeyPathError(f'{role} "{text}" indexes an array with {segment!r}')
    return int(segment)


def resolve_all(schema, spec, role):
    """Resolve a comma-separated list of paths."""
    return tuple(parse_path(schema, text, role) for text in spec.split(","))

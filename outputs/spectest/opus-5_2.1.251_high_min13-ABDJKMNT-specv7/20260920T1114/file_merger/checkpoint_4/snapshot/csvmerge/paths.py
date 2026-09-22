"""Field paths: `user.id`, `items.0.sku`, `attrs["country"]`.

A path names one primitive leaf of the output schema. Parsing splits the text
into steps, resolving checks each step against the declared types — turning a
numeric step into an array index — and `FieldPath.read` walks a casted record,
reading anything missing as null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from csvmerge.errors import EXIT_SCHEMA, MergeError
from csvmerge.schema import Schema
from csvmerge.typespec import Array, DataType, Map, Primitive, Struct

_COLUMN = re.compile(r"[^.\[]*")
_BRACKET = re.compile(r'\["((?:[^"\\]|\\.)*)"\]')
_DOTTED = re.compile(r"\.([^.\[]+)")
_ESCAPED = re.compile(r"\\(.)")


@dataclass(frozen=True)
class MapKey:
    """A bracketed map lookup, as opposed to a dotted field name."""

    key: str


Step = str | int | MapKey


@dataclass(frozen=True)
class FieldPath:
    """A `--key` or `--partition-by` path resolved against the schema."""

    text: str
    column: str
    steps: tuple[Step, ...]
    type: Primitive

    def read(self, record: dict[str, object]) -> object:
        """The value this path names in a casted record, null where missing."""
        value = record.get(self.column)
        for step in self.steps:
            value = _read(value, step)
        return value


def split_paths(text: str) -> list[str]:
    """Split a comma-separated path list, ignoring commas inside `"..."` keys."""
    paths, quoted, start = [], False, 0
    for index, character in enumerate(text):
        if character == '"':
            quoted = not quoted
        elif character == "," and not quoted:
            paths.append(text[start:index])
            start = index + 1
    paths.append(text[start:])
    return paths


def resolve(text: str, schema: Schema, role: str) -> FieldPath:
    """Check one path against the schema and record how to read its leaf.

    A column whose own name contains dots wins over reading that name as a
    path, so flat schemas keep working unchanged (ambiguity T55).
    """
    declared = schema.type_of(text)
    if declared is not None:
        return _leaf(text, text, (), declared, role)
    column, raw_steps = _scan(text, role)
    declared = schema.type_of(column)
    if declared is None:
        raise MergeError(
            f'{role} column "{text}" is not in the resolved schema', EXIT_SCHEMA
        )
    steps = []
    for raw in raw_steps:
        step, declared = _descend(raw, declared, text, role)
        steps.append(step)
    return _leaf(text, column, tuple(steps), declared, role)


def _leaf(
    text: str, column: str, steps: tuple[Step, ...], declared: DataType, role: str
) -> FieldPath:
    """Accept a fully resolved path, provided it ends on a primitive."""
    if not isinstance(declared, Primitive):
        raise MergeError(
            f'{role} column "{text}" does not resolve to a primitive', EXIT_SCHEMA
        )
    return FieldPath(text, column, steps, declared)


def _scan(text: str, role: str) -> tuple[str, list[Step]]:
    """Split path text into its column name and its unresolved steps."""
    column = _COLUMN.match(text).group()
    steps, position = [], len(column)
    while position < len(text):
        bracket = _BRACKET.match(text, position)
        dotted = None if bracket else _DOTTED.match(text, position)
        if bracket:
            steps.append(MapKey(_ESCAPED.sub(r"\1", bracket.group(1))))
        elif dotted:
            steps.append(dotted.group(1))
        else:
            raise MergeError(
                f'{role} column "{text}" is not a valid field path', EXIT_SCHEMA
            )
        position = (bracket or dotted).end()
    return column, steps


def _descend(
    step: Step, declared: DataType, text: str, role: str
) -> tuple[Step, DataType]:
    """Follow one step, reporting the type the rest of the path continues from."""
    if isinstance(declared, Struct) and isinstance(step, str):
        field = next((one for one in declared.fields if one.name == step), None)
        if field is not None:
            return step, field.type
    elif isinstance(declared, Array) and isinstance(step, str):
        return _index(step, text, role), declared.element
    elif isinstance(declared, Map) and isinstance(step, MapKey):
        return step, declared.value
    raise MergeError(
        f'{role} column "{text}" cannot read {_describe(step)} from {declared.text}',
        EXIT_SCHEMA,
    )


def _index(step: str, text: str, role: str) -> int:
    """An array index; the spec allows non-negative integers only."""
    if not step.isdigit():
        raise MergeError(
            f'{role} column "{text}" indexes an array with {step!r}, '
            "which is not a non-negative integer",
            EXIT_SCHEMA,
        )
    return int(step)


def _describe(step: Step) -> str:
    return f"key {step.key!r}" if isinstance(step, MapKey) else f"field {step!r}"


def _read(value: object, step: Step) -> object:
    """Read one step from a casted value; anything absent reads as null."""
    if isinstance(step, MapKey):
        return value.get(step.key) if isinstance(value, dict) else None
    if isinstance(step, int):
        within = isinstance(value, list) and step < len(value)
        return value[step] if within else None
    return value.get(step) if isinstance(value, dict) else None

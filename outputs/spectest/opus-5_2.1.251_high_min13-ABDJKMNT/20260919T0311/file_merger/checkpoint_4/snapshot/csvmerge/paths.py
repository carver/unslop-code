"""Field paths: how `--key` and `--partition-by` name a value inside a column.

A path is a column name followed by segments that traverse structs, arrays and
maps — `user.id`, `items.0.sku`, `attrs["country"]`. Each one is resolved
against the schema before any input is read, so a path that cannot reach a
primitive fails the run rather than one row of it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .errors import EXIT_SCHEMA, MergeError
from .schema import Schema
from .types import Array, Map, Struct, TypeExpr, is_primitive
from .values import Cell, leaf_fragment


@dataclass(frozen=True)
class Step:
    """One segment of a path: a struct field, an array index, or a map key."""

    text: str

    def read(self, value: Any) -> Any:
        """The value this step names, or `None` when it names nothing."""
        if isinstance(value, dict):
            return value.get(self.text)
        if isinstance(value, list):
            index = int(self.text)
            return value[index] if index < len(value) else None
        return None


@dataclass(frozen=True)
class FieldPath:
    """A path bound to a column of the resolved schema and to its leaf type."""

    text: str
    column: int
    steps: tuple[Step, ...]
    leaf_type: str

    def fragment(self, cells: Sequence[Cell]) -> tuple[str | None, list]:
        """This path's partition text and sort key part for one row's cells."""
        value = cells[self.column].value
        for step in self.steps:
            value = step.read(value)
        return leaf_fragment(value, self.leaf_type)


def split_paths(text: str) -> list[str]:
    """Split a comma-separated path list, ignoring commas inside `["..."]`."""
    paths, depth, start = [], 0, 0
    for position, character in enumerate(text):
        depth += (character == "[") - (character == "]")
        if character == "," and depth == 0:
            paths.append(text[start:position])
            start = position + 1
    paths.append(text[start:])
    return paths


def resolve_paths(texts: Sequence[str], schema: Schema, role: str) -> list[FieldPath]:
    """Bind every `--key` or `--partition-by` path to the schema it will read."""
    missing = [text for text in texts if _column_name(text) not in schema.names]
    if missing:
        raise MergeError(
            f"{role} column(s) not in the resolved schema: {', '.join(missing)}", EXIT_SCHEMA
        )
    return [_resolve(text, schema) for text in texts]


def _resolve(text: str, schema: Schema) -> FieldPath:
    name, steps = _parse(text)
    index = schema.names.index(name)
    type_expr = schema.columns[index].type
    for step in steps:
        type_expr = _descend(type_expr, step, text)
    if not is_primitive(type_expr):
        raise _not_primitive(text)
    return FieldPath(text, index, steps, type_expr)


def _descend(type_expr: TypeExpr, step: Step, text: str) -> TypeExpr:
    """The declared type of one step of a path, whatever kind it steps into."""
    if isinstance(type_expr, Struct):
        fields = {field.name: field.type for field in type_expr.fields}
        if step.text not in fields:
            raise _not_primitive(text)
        return fields[step.text]
    if isinstance(type_expr, Array):
        if not step.text.isdigit():
            raise _not_primitive(text)
        return type_expr.element
    if isinstance(type_expr, Map):
        return type_expr.value
    raise _not_primitive(text)


def _not_primitive(text: str) -> MergeError:
    return MergeError(f'key column "{text}" does not resolve to a primitive', EXIT_SCHEMA)


def _parse(text: str) -> tuple[str, tuple[Step, ...]]:
    """Split a path into its column name and its steps.

    Dots separate segments; a `["..."]` lookup is a segment of its own, so that
    a map key may contain dots, commas or spaces.
    """
    segments, current, position = [], "", 0
    while position < len(text):
        character = text[position]
        if character == ".":
            segments.append(current)
            current = ""
        elif character == "[":
            end = text.find("]", position)
            segments.append(current)
            current = ""
            segments.append(_unquote(text[position + 1:end if end > 0 else len(text)]))
            position = (end if end > 0 else len(text))
        else:
            current += character
        position += 1
    segments.append(current)
    name, *steps = [segment for segment in segments if segment != ""] or [""]
    return name, tuple(Step(step) for step in steps)


def _unquote(key: str) -> str:
    """The text of a bracketed key, with its surrounding quotes removed."""
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        return key[1:-1]
    return key


def _column_name(text: str) -> str:
    return _parse(text)[0]

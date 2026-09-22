"""Field paths: how ``--key`` and ``--partition-by`` name a value in a row.

A path starts at a column and then walks into whatever that column declares:
``.name`` picks a struct field, ``.0`` an array element and ``["key"]`` a map
entry.  Resolving a path against the schema settles what each step means and
checks that the path ends on a primitive, so reading it out of a cast row is
just a chain of lookups.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, NamedTuple, Sequence

from .coltypes import ColumnType
from .datatypes import ArrayType, DataType, MapType, StructType
from .errors import KeyColumnError, UsageError
from .schema import Schema

#: A step is ``.name`` — a struct field or an array index — or a bracketed,
#: double-quoted map key.  The column name at the front of a path matches the
#: same characters as a dotted step.
_NAME = re.compile(r'[^.\[\]"]+')
_STEP = re.compile(r'\.([^.\[\]"]+)|\[("(?:[^"\\]|\\.)*")\]')


class _Token(NamedTuple):
    """One parsed step: ``quoted`` marks the bracketed map-key spelling."""

    quoted: bool
    text: str


@dataclass(frozen=True)
class Get:
    """Reads a struct field or a map entry out of an object."""

    name: str

    def read(self, value: Any) -> Any:
        return value.get(self.name) if isinstance(value, dict) else None


@dataclass(frozen=True)
class Index:
    """Reads one element of an array; out of range reads as null."""

    position: int

    def read(self, value: Any) -> Any:
        if isinstance(value, list) and self.position < len(value):
            return value[self.position]
        return None


@dataclass(frozen=True)
class ResolvedPath:
    """A field path bound to a column of the schema and to a primitive type."""

    text: str
    column: int
    steps: tuple[Get | Index, ...]
    type: ColumnType

    def read(self, values: Sequence[Any]) -> Any:
        """Pull this path's value out of one cast row."""
        value = values[self.column]
        for step in self.steps:
            value = step.read(value)
        return value


def resolve_paths(texts: Sequence[str], schema: Schema, role: str = "key") -> list[ResolvedPath]:
    """Resolve every ``--key`` or ``--partition-by`` path against the schema."""
    return [_resolve(text, schema, role) for text in texts]


def _resolve(text: str, schema: Schema, role: str) -> ResolvedPath:
    """Bind one path to its column and settle what each of its steps means."""
    column, tokens = _scan(text)
    names = schema.names
    if column not in names:
        raise KeyColumnError(
            f"{role} column(s) {column} are not in the resolved schema: {', '.join(names)}"
        )
    position = names.index(column)
    datatype = schema.columns[position].type
    steps: list[Get | Index] = []
    for token in tokens:
        step, datatype = _step(token, datatype, text, role)
        steps.append(step)
    if not isinstance(datatype, ColumnType):
        raise KeyColumnError(f'{role} column "{text}" does not resolve to a primitive')
    return ResolvedPath(text, position, tuple(steps), datatype)


def _step(
    token: _Token, datatype: DataType, text: str, role: str
) -> tuple[Get | Index, DataType]:
    """Interpret one step against the type it is applied to."""
    if isinstance(datatype, MapType) and token.quoted:
        return Get(token.text), datatype.value
    if isinstance(datatype, StructType) and not token.quoted:
        field = datatype.field(token.text)
        if field is not None:
            return Get(field.name), field.type
    if isinstance(datatype, ArrayType) and not token.quoted and token.text.isdigit():
        return Index(int(token.text)), datatype.element
    raise KeyColumnError(f'{role} column "{text}" does not resolve to a primitive')


def _scan(text: str) -> tuple[str, list[_Token]]:
    """Split a path into its column name and its steps."""
    head = _NAME.match(text)
    if head is None:
        raise UsageError(f"{text!r} is not a field path: it does not start with a column name")
    tokens = []
    position = head.end()
    while position < len(text):
        step = _STEP.match(text, position)
        if step is None:
            raise UsageError(
                f"{text!r} is not a field path: expected '.name' or '[\"key\"]' at "
                f"{text[position:]!r}"
            )
        name, quoted = step.groups()
        tokens.append(
            _Token(False, name) if quoted is None else _Token(True, json.loads(quoted))
        )
        position = step.end()
    return head.group(), tokens

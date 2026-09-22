"""Casting an input value to its declared type, and spelling the result.

A casted value is a tree of plain Python objects: primitives as the parsers in
`csvmerge.types` produce them, structs and maps as dictionaries already in
output order, arrays as lists, and `Kept` wherever `--on-type-error
keep-string` held on to text that would not cast. `render` turns such a tree
into the text of one CSV cell — canonical JSON for everything nested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from csvmerge.errors import EXIT_TYPE, MergeError
from csvmerge.types import TYPES
from csvmerge.typespec import AnyJson, Array, DataType, Map, Primitive, Struct
from csvmerge.values import canonical_text

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"

_TIMESTAMP = TYPES["timestamp"]


@dataclass(frozen=True)
class Kept:
    """Text that `--on-type-error keep-string` kept after a failed cast."""

    text: str


@dataclass(frozen=True)
class Origin:
    """Where a record came from, as the `file=... line=...` of a message."""

    path: str
    line: int

    def __str__(self) -> str:
        return f"file={self.path} line={self.line}"


@dataclass(frozen=True)
class CastContext:
    """The error policy in force and the record currently being cast."""

    policy: str
    origin: Origin

    def failed(self, value: object, declared: DataType, path: str) -> object:
        """Apply `--on-type-error` to a value that will not cast."""
        text = value if isinstance(value, str) else encode_json(value)
        if self.policy == FAIL:
            raise MergeError(
                f'cannot cast "{text}" to {declared.text} in field "{path}" '
                f"({self.origin})",
                EXIT_TYPE,
            )
        return Kept(text) if self.policy == KEEP_STRING else None


def cast(value: object, declared: DataType, path: str, context: CastContext) -> object:
    """Cast one value to its declared type, recursing into nested types."""
    if value is None:
        return None
    if isinstance(declared, AnyJson):
        return normalise(value)
    if isinstance(declared, Struct):
        return _cast_struct(value, declared, path, context)
    if isinstance(declared, Array):
        return _cast_array(value, declared, path, context)
    if isinstance(declared, Map):
        return _cast_map(value, declared, path, context)
    return _cast_primitive(value, declared, path, context)


def normalise(value: object) -> object:
    """A `json` value's canonical form: nothing is cast, object keys sort."""
    if isinstance(value, dict):
        return {key: normalise(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalise(item) for item in value]
    return value


def render(value: object, declared: DataType) -> str | None:
    """The output text of a casted value, or None when the value is null."""
    if value is None:
        return None
    if isinstance(value, Kept):
        return value.text
    if isinstance(declared, Primitive):
        return declared.definition.render(value)
    return encode_json(value)


def encode_json(value: object) -> str:
    """Minified RFC 8259 JSON, UTF-8, with the spec's temporal spellings."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_leaf)


def _cast_struct(value: object, declared: Struct, path: str, context: CastContext):
    """Every declared field, in declared order, missing ones included as null."""
    if not isinstance(value, dict):
        return context.failed(value, declared, path)
    return {
        field.name: cast(
            value.get(field.name), field.type, f"{path}.{field.name}", context
        )
        for field in declared.fields
    }


def _cast_array(value: object, declared: Array, path: str, context: CastContext):
    """Every element cast to the element type, in its original position."""
    if not isinstance(value, list):
        return context.failed(value, declared, path)
    return [
        cast(item, declared.element, f"{path}.{index}", context)
        for index, item in enumerate(value)
    ]


def _cast_map(value: object, declared: Map, path: str, context: CastContext):
    """Every entry of a string-keyed object, the keys sorted for the output."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return context.failed(value, declared, path)
    return {
        key: cast(value[key], declared.value, f'{path}["{key}"]', context)
        for key in sorted(value)
    }


def _cast_primitive(
    value: object, declared: Primitive, path: str, context: CastContext
):
    """Spell the value as text, then parse it the way its type asks."""
    if isinstance(value, (dict, list)):
        return context.failed(value, declared, path)
    text = canonical_text(value)
    try:
        return declared.definition.parse(text)
    except ValueError:
        return context.failed(text, declared, path)


def _normalised_timestamp(value: datetime) -> str:
    """A timestamp from a typed source, re-spelled as UTC with a Z suffix."""
    return _TIMESTAMP.render(_TIMESTAMP.parse(value.isoformat()))


_LEAVES = {
    date: date.isoformat,
    datetime: _normalised_timestamp,
    Kept: lambda value: value.text,
}


def _leaf(value: object) -> str:
    """Spell one value `json.dumps` cannot encode on its own."""
    return _LEAVES.get(type(value), canonical_text)(value)

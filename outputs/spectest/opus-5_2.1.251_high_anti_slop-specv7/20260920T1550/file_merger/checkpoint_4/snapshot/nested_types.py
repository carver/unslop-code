"""The nested types a column can hold: structs, arrays and maps, plus ``json``.

A nested value is cast recursively — every leaf goes through the primitive
types of :mod:`column_types`, so the same parsing rules and the same
``--on-type-error`` handling apply however deep it sits — and is written to its
CSV cell as canonical JSON: minified, struct fields in the order the schema
declares them, map keys sorted lexicographically and array elements left in the
order they arrived in.

``json`` is the way out of a declared shape: it accepts any JSON value and
normalises it instead of casting it, so a column whose contents vary from row
to row still lands in the output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from casting import CastContext, KeptText, ValueType, compact_json, json_form
from column_types import canonical_text
from records import FieldValue


class NestedType:
    """A type whose values are written to a CSV cell as canonical JSON.

    Each of them supplies its own ``to_json``, which is where the ordering of
    fields, keys and elements is settled.
    """

    def render(self, value: object) -> str:
        """The canonical JSON text of a cast value of this type."""
        return compact_json(self.to_json(value))


@dataclass(frozen=True)
class StructField:
    """One named field of a struct and the type declared for it."""

    name: str
    type: ValueType


@dataclass(frozen=True)
class StructType(NestedType):
    """An ordered group of named fields, written as a JSON object.

    Every declared field is written, an absent one as an explicit ``null``, and
    a field the schema does not declare is dropped.
    """

    fields: tuple[StructField, ...]

    @property
    def name(self) -> str:
        return "struct"

    def field_type(self, name: str) -> ValueType | None:
        """The type declared for ``name``, or ``None`` if there is no such field."""
        return next((field.type for field in self.fields if field.name == name), None)

    def cast(self, value: FieldValue, context: CastContext) -> object:
        source = _structure(value, dict, self, context)
        if not isinstance(source, dict):
            return source
        return {
            field.name: field.type.cast(source.get(field.name), context.child(field.name))
            for field in self.fields
        }

    def to_json(self, value: object) -> object:
        return {field.name: json_form(field.type, value[field.name]) for field in self.fields}


@dataclass(frozen=True)
class ArrayType(NestedType):
    """A JSON array whose elements all have the same type."""

    element: ValueType

    @property
    def name(self) -> str:
        return f"array<{self.element.name}>"

    def cast(self, value: FieldValue, context: CastContext) -> object:
        source = _structure(value, list, self, context)
        if not isinstance(source, list):
            return source
        return [self.element.cast(item, context.child(index)) for index, item in enumerate(source)]

    def to_json(self, value: object) -> object:
        return [json_form(self.element, item) for item in value]


@dataclass(frozen=True)
class MapType(NestedType):
    """A JSON object with string keys and one type for all of its values."""

    value: ValueType

    @property
    def name(self) -> str:
        return f"map<string,{self.value.name}>"

    def cast(self, value: FieldValue, context: CastContext) -> object:
        source = _structure(value, dict, self, context)
        if not isinstance(source, dict):
            return source
        entries = ((canonical_text(key), entry) for key, entry in source.items())
        return {key: self.value.cast(entry, context.child(key)) for key, entry in entries}

    def to_json(self, value: object) -> object:
        return {key: json_form(self.value, entry) for key, entry in sorted(value.items())}


class JsonType(NestedType):
    """A column that takes any JSON value and is normalised rather than cast."""

    name = "json"

    def cast(self, value: FieldValue, context: CastContext) -> object:
        if value is None:
            return None
        if isinstance(value, str) and context.text_cells:
            return _decoded(value, self, context)
        return value

    def to_json(self, value: object) -> object:
        """Normalise the value: object keys sorted, anything typed as its text.

        A value that arrived typed, a Parquet date among them, has no JSON form
        of its own and becomes its canonical text.
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {
                canonical_text(key): self.to_json(entry) for key, entry in sorted(value.items())
            }
        if isinstance(value, list):
            return [self.to_json(item) for item in value]
        return canonical_text(value)


JSON = JsonType()


def _decoded(text: str, declared: ValueType, context: CastContext) -> object:
    """Read the single JSON literal a CSV or TSV cell has to hold."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return context.recover(text, declared.name)


def _structure(
    value: FieldValue, shape: type, declared: ValueType, context: CastContext
) -> object:
    """The JSON object or array ``value`` holds, or what recovery made of it.

    Text inputs hold their nested values as JSON text, typed inputs hand over
    the object or the array itself.  A value that is not the ``shape`` the type
    asks for follows ``--on-type-error``, so the caller recognises a recovered
    value by it not being that shape.
    """
    if value is None:
        return None
    if isinstance(value, str) and context.text_cells:
        value = _decoded(value, declared, context)
    if isinstance(value, shape) or value is None or isinstance(value, KeptText):
        return value
    return context.recover(canonical_text(value), declared.name)

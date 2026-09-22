"""Casting source values into their declared types under `--on-type-error`.

Records hold raw text from CSV/TSV and native objects from JSONL/Parquet, and a
declared type may be nested arbitrarily deep, so casting walks the type and the
value together. Every level recovers on its own: a field that will not cast is
nulled, kept as text, or fails the run, without disturbing its siblings.
"""

from __future__ import annotations

import json

from .coltypes import CastError, KeptText, canonical_json, render
from .errors import CastFailure
from .typespec import AnyJson, Array, Map, Primitive, Struct
from .values import cast_value, native

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"
POLICIES = (COERCE_NULL, FAIL, KEEP_STRING)


class ValueCaster:
    """Casts one value into a declared type, recovering per `--on-type-error`."""

    def __init__(self, policy):
        self._policy = policy

    def cast_column(self, column, value, origin):
        """Cast a whole column value, given where the record came from.

        A delimited source hands over text, so a nested or `json` column's cell is
        the JSON literal holding the value; every other source already has one.
        """
        if value is None:
            return None
        if origin.delimited and not isinstance(column.type, Primitive):
            try:
                value = json.loads(value)
            except ValueError:
                return self._recover(column.type, value, column.name, origin)
        return self.cast(column.type, value, column.name, origin)

    def cast(self, declared, value, path, origin):
        """Cast `value` into `declared`, naming it `path` if that fails."""
        if value is None:
            return None
        try:
            return self._cast(declared, value, path, origin)
        except CastError:
            return self._recover(declared, value, path, origin)

    def _cast(self, declared, value, path, origin):
        if isinstance(declared, AnyJson):
            return normalize(value)
        if isinstance(declared, Struct):
            return self._cast_struct(declared, _mapping(value), path, origin)
        if isinstance(declared, Array):
            return [
                self.cast(declared.element, element, f"{path}.{position}", origin)
                for position, element in enumerate(_sequence(value))
            ]
        if isinstance(declared, Map):
            return self._cast_map(declared, _mapping(value), path, origin)
        if isinstance(value, (dict, list)):
            raise CastError(f"not a {declared.name}: {value!r}")
        return cast_value(declared.name, native(value))

    def _cast_struct(self, declared, value, path, origin):
        """Every declared field, in order, with the undeclared keys dropped."""
        return {
            field.name: self.cast(field.type, value.get(field.name), f"{path}.{field.name}", origin)
            for field in declared.fields
        }

    def _cast_map(self, declared, value, path, origin):
        """Map entries, keyed by text and ordered lexicographically."""
        return {
            str(key): self.cast(declared.value, value[key], f"{path}.{key}", origin)
            for key in sorted(value, key=str)
        }

    def _recover(self, declared, value, path, origin):
        """Apply the policy to a value that would not cast into `declared`."""
        text = stringify(value)
        if self._policy == FAIL:
            raise CastFailure(
                f'cannot cast "{text}" to {declared.label} in field "{path}" ({origin})'
            )
        return KeptText(text) if self._policy == KEEP_STRING else None


class RowCaster:
    """Casts whole records into the resolved schema's columns."""

    def __init__(self, schema, policy):
        self._columns = schema.columns
        self._values = ValueCaster(policy)

    def cast_row(self, record, origin):
        """Return one value per schema column, in schema order."""
        return [
            self._values.cast_column(column, record.get(column.name), origin)
            for column in self._columns
        ]

    def render_row(self, values, null_literal):
        """Render a row's cast values as the text of its CSV cells."""
        return [
            _cell(column.type, value, null_literal)
            for column, value in zip(self._columns, values)
        ]


def _cell(declared, value, null_literal):
    """Render one cast value as its cell.

    A `json` column emits JSON text whatever the value's shape, so a scalar keeps
    its JSON spelling; text kept by `keep-string` is emitted as it arrived.
    """
    if isinstance(declared, AnyJson) and value is not None and not isinstance(value, KeptText):
        return canonical_json(value)
    return render(value, null_literal)


def normalize(value):
    """Prepare a `json` value for output: order object keys, cast nothing."""
    if isinstance(value, dict):
        return {str(key): normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [normalize(element) for element in value]
    return native(value)


def stringify(value):
    """The text `keep-string` substitutes, and the `<val>` an `ERR 4` quotes."""
    return canonical_json(value) if isinstance(value, (dict, list)) else render(value, "")


def _mapping(value):
    """A struct or map value, as read from JSON or as Parquet's list of pairs."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and all(_is_pair(element) for element in value):
        return dict(value)
    raise CastError(f"not an object: {value!r}")


def _sequence(value):
    if isinstance(value, list):
        return value
    raise CastError(f"not an array: {value!r}")


def _is_pair(element):
    return isinstance(element, tuple) and len(element) == 2

"""Casting one input cell into a typed value, and rendering it back out.

A primitive column casts its cell the way the earlier checkpoints did. A nested
column first obtains a JSON value - decoded by the reader, or parsed out of a
delimited cell that must hold a single JSON literal - and then casts it
recursively against the declared type, field by field and element by element.
Rendering is the mirror image: primitives render as their own text, nested
values as canonical JSON.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from .casting import CastError, RawText, cast, render_timestamp, render_value
from .datatypes import AnyJson, Array, Mapping, Primitive, Struct
from .records import JsonValue, scalar_text

_JSON_TEXT = {"ensure_ascii": False, "separators": (",", ":")}


class JsonCellError(ValueError):
    """A cell that has to hold a JSON literal but does not.

    The message is the body of the spec's ``ERR 5`` line; the reader adds the
    file and line it came from.
    """

    def __init__(self, path: str):
        super().__init__(f'invalid JSON in field "{path}"')


def cast_cell(cell, datatype, on_type_error: str, path: str):
    """Cast one non-null cell into the value its column type declares."""
    if isinstance(cell, JsonValue):
        return _cast_value(cell.value, datatype, on_type_error, path)
    if isinstance(datatype, Primitive):
        return cast(cell, datatype.spec, on_type_error, path)
    return _cast_value(_parsed(cell, on_type_error, path), datatype, on_type_error, path)


def render_cell(value, datatype, null_literal: str) -> str:
    """Render a cast value as the text of its output cell."""
    if value is None:
        return null_literal
    if isinstance(datatype, Primitive):
        return render_value(value, datatype.spec)
    if isinstance(value, RawText):
        return str(value)  # a cell kept verbatim because it held no JSON literal
    return json.dumps(_encodable(value, datatype), **_JSON_TEXT)


def _parsed(text: str, on_type_error: str, path: str):
    """Read the single JSON literal a delimited cell must hold."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if on_type_error == "fail":
            raise JsonCellError(path) from None
        return RawText(text) if on_type_error == "keep-string" else None


def _cast_value(value, datatype, on_type_error: str, path: str):
    """Cast one JSON value, descending into the structures the type declares."""
    if value is None or isinstance(value, RawText) or isinstance(datatype, AnyJson):
        return value  # a null, a cell kept verbatim, or a `json` column: nothing to cast
    if isinstance(datatype, Primitive):
        return _cast_scalar(value, datatype, on_type_error, path)
    if isinstance(datatype, Struct) and isinstance(value, dict):
        return {
            name: _cast_value(value.get(name), field, on_type_error, f"{path}.{name}")
            for name, field in datatype.fields
        }
    if isinstance(datatype, Array) and isinstance(value, list):
        return [
            _cast_value(item, datatype.element, on_type_error, f"{path}.{position}")
            for position, item in enumerate(value)
        ]
    if isinstance(datatype, Mapping) and isinstance(value, dict):
        return {
            key: _cast_value(item, datatype.value, on_type_error, f'{path}["{key}"]')
            for key, item in value.items()
        }
    return _unfit(value, datatype, on_type_error, path)


def _cast_scalar(value, datatype: Primitive, on_type_error: str, path: str):
    """Cast a JSON scalar through the primitive rules; a structure cannot fit."""
    if isinstance(value, (dict, list)):
        return _unfit(value, datatype, on_type_error, path)
    return cast(scalar_text(value), datatype.spec, on_type_error, path)


def _unfit(value, datatype, on_type_error: str, path: str):
    """Apply the type error policy to a value of the wrong shape for its type."""
    text = value if isinstance(value, str) else json.dumps(value, **_JSON_TEXT)
    if on_type_error == "fail":
        raise CastError(text, datatype.label, path)
    return RawText(text) if on_type_error == "keep-string" else None


def _encodable(value, datatype):
    """Project a cast value onto the JSON shapes ``json.dumps`` writes out.

    Structs keep their declared field order, maps sort their keys, arrays keep
    theirs, and temporal values become their normalised text.
    """
    if value is None:
        return None
    if isinstance(value, RawText):
        return str(value)
    if isinstance(datatype, AnyJson):
        return _normalized(value)
    if isinstance(datatype, Struct):
        return {name: _encodable(value.get(name), field) for name, field in datatype.fields}
    if isinstance(datatype, Array):
        return [_encodable(item, datatype.element) for item in value]
    if isinstance(datatype, Mapping):
        return {key: _encodable(value[key], datatype.value) for key in sorted(value)}
    return _temporal(value)


def _normalized(value):
    """Canonicalise a value of a ``json`` column: objects sort, the rest stands."""
    if isinstance(value, dict):
        return {key: _normalized(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _temporal(value):
    """The JSON text of a date or timestamp; every other scalar is itself."""
    if isinstance(value, datetime):
        return render_timestamp(value)
    return value.isoformat() if isinstance(value, date) else value

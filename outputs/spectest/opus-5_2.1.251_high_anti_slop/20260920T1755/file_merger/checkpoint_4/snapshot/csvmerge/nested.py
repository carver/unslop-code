"""Casting values into a nested type, and rendering them as canonical JSON.

Casting walks the declared type and the value together, so every leaf ends up
as a cast primitive and every container ends up in its canonical order:
struct fields in the order the schema declares them, map and ``json`` object
keys sorted lexicographically, array elements left where they were. Rendering
is then a plain dump of that structure, which is what a nested column's CSV
cell holds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from csvmerge.errors import MergeError
from csvmerge.types import Array, DataType, Json, Primitive, Struct
from csvmerge.values import cast_value, format_value

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"


@dataclass(frozen=True)
class CastContext:
    """What a failing cast needs to know: the policy, and where the value came from."""

    on_type_error: str
    location: str


def cast_field(value: Any, declared: DataType, path: str, context: CastContext) -> Any:
    """Cast ``value`` to ``declared``, recursing into every nested level.

    ``path`` is the dotted field path of ``value`` within its row, which is
    how a failure deep inside a structure names itself.
    """
    if value is None:
        return None
    if isinstance(declared, Json):
        return normalise(value)
    if isinstance(declared, Primitive):
        if isinstance(value, (dict, list)):
            return _failed(value, declared, path, context)
        parsed, result = cast_value(value, declared.name)
        return result if parsed else _failed(value, declared, path, context)
    if isinstance(declared, Struct):
        if not isinstance(value, dict):
            return _failed(value, declared, path, context)
        return {
            field.name: cast_field(
                value.get(field.name), field.type, f"{path}.{field.name}", context
            )
            for field in declared.fields
        }
    if isinstance(declared, Array):
        if not isinstance(value, list):
            return _failed(value, declared, path, context)
        return [
            cast_field(element, declared.element, f"{path}.{index}", context)
            for index, element in enumerate(value)
        ]
    # Every other kind is handled above, so what is left is a map.
    members = _as_mapping(value)
    if members is None:
        return _failed(value, declared, path, context)
    return {
        key: cast_field(members[key], declared.value, f'{path}["{key}"]', context)
        for key in sorted(members)
    }


def parse_json_cell(text: str, declared: DataType, path: str, context: CastContext) -> Any:
    """Read a text cell holding a nested value: one JSON literal, or nothing."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return _failed(text, declared, path, context)
    return cast_field(value, declared, path, context)


def to_json_text(value: Any) -> str:
    """Render a cast value as minified UTF-8 JSON, keys already in order."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_leaf_text)


def normalise(value: Any) -> Any:
    """Put an uncast JSON value in canonical order, sorting every object's keys."""
    if isinstance(value, dict):
        return {key: normalise(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [normalise(element) for element in value]
    return value


def _failed(value: Any, declared: DataType, path: str, context: CastContext) -> Any:
    """Apply ``--on-type-error`` to a value that will not cast to ``declared``."""
    if context.on_type_error == FAIL:
        raise MergeError(
            f"{context.location}: cannot cast {value!r} to {declared} for field {path!r}"
        )
    if context.on_type_error == KEEP_STRING:
        return value if isinstance(value, str) else to_json_text(normalise(value))
    return None


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    """Read a map value, which Parquet hands over as a list of key-value pairs."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and all(isinstance(pair, tuple) and len(pair) == 2 for pair in value):
        return dict(value)
    return None


def _leaf_text(value: Any) -> str:
    """Spell a cast date or timestamp the way a flat column would."""
    return format_value(value, "")

"""Validating a model response against a task's `output_schema`.

Supports the JSON Schema draft 7 keywords the spec lists - `type`, `required`,
`properties`, `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`
and `pattern` - and reports the first failure as a human-readable message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

#: How each draft 7 `type` name matches a parsed JSON value.
TYPES = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    # "1.0 is an integer" in draft 7, unlike Python's isinstance check.
    "integer": lambda value: (
        isinstance(value, int) and not isinstance(value, bool)
        or isinstance(value, float) and value.is_integer()
    ),
}


@dataclass(frozen=True)
class SchemaCheck:
    """The verdict on one response: the parsed value, or why it was rejected."""

    valid: bool
    value: object = None
    error: str | None = None


def check_response(schema: dict, text: str | None) -> SchemaCheck:
    """Parse ``text`` as JSON and validate it; invalid JSON is a schema failure."""
    if text is None:
        return SchemaCheck(False, error="No response to validate")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return SchemaCheck(False, error=f"Invalid JSON: {exc}")

    error = validate(schema, value)
    return SchemaCheck(error is None, value if error is None else None, error)


def validate(schema: dict, value, field: str = "") -> str | None:
    """The first violation of ``schema`` by ``value``, or ``None`` if it conforms."""
    for keyword, check in _KEYWORDS.items():
        if keyword in schema:
            error = check(schema[keyword], value, field)
            if error is not None:
                return error
    return None


def _where(field: str) -> str:
    """Message prefix naming the field a violation was found in."""
    return f"field '{field}': " if field else ""


def _type(expected, value, field: str) -> str | None:
    names = expected if isinstance(expected, list) else [expected]
    if any(TYPES[name](value) for name in names if name in TYPES):
        return None
    return f"{_where(field)}expected type {' or '.join(names)}, got {_name(value)}"


def _name(value) -> str:
    """The draft 7 type name of a parsed JSON value, for error messages."""
    return next((name for name, matches in TYPES.items() if matches(value)), "null")


def _required(names, value, field: str) -> str | None:
    if not isinstance(value, dict):
        return None
    prefix = f"{field}." if field else ""
    missing = [name for name in names if name not in value]
    if missing:
        return f"Missing required field: {prefix}{missing[0]}"
    return None


def _properties(properties: dict, value, field: str) -> str | None:
    if not isinstance(value, dict):
        return None
    prefix = f"{field}." if field else ""
    for name, subschema in properties.items():
        if name in value:
            error = validate(subschema, value[name], f"{prefix}{name}")
            if error is not None:
                return error
    return None


def _items(subschema: dict, value, field: str) -> str | None:
    if not isinstance(value, list):
        return None
    label = field or "items"
    for index, element in enumerate(value):
        error = validate(subschema, element, f"{label}[{index}]")
        if error is not None:
            return error
    return None


def _enum(allowed: list, value, field: str) -> str | None:
    if value in allowed:
        return None
    return f"{_where(field)}{value!r} is not one of {allowed}"


def _minimum(bound, value, field: str) -> str | None:
    if _numeric(value) and value < bound:
        return f"{_where(field)}{value} is less than minimum {bound}"
    return None


def _maximum(bound, value, field: str) -> str | None:
    if _numeric(value) and value > bound:
        return f"{_where(field)}{value} is greater than maximum {bound}"
    return None


def _min_length(bound, value, field: str) -> str | None:
    if isinstance(value, str) and len(value) < bound:
        return f"{_where(field)}length {len(value)} is less than minLength {bound}"
    return None


def _max_length(bound, value, field: str) -> str | None:
    if isinstance(value, str) and len(value) > bound:
        return f"{_where(field)}length {len(value)} is greater than maxLength {bound}"
    return None


def _pattern(pattern: str, value, field: str) -> str | None:
    if isinstance(value, str) and re.search(pattern, value) is None:
        return f"{_where(field)}{value!r} does not match pattern {pattern!r}"
    return None


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


#: Checked in this order, so a type mismatch is reported before anything else.
_KEYWORDS = {
    "type": _type,
    "enum": _enum,
    "required": _required,
    "properties": _properties,
    "items": _items,
    "minimum": _minimum,
    "maximum": _maximum,
    "minLength": _min_length,
    "maxLength": _max_length,
    "pattern": _pattern,
}

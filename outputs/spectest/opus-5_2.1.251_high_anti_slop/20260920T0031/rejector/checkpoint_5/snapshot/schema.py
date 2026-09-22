"""Structured output: parsing a response as JSON and validating it against a schema.

The supported vocabulary is the draft 7 subset a task's `output_schema` may use:
`type`, `required`, `properties`, `items`, `enum`, `minimum`, `maximum`,
`minLength`, `maxLength` and `pattern`. Validation reports the first constraint
a response breaks, phrased for a human reading the result row.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

#: JSON Schema type names and the Python types that satisfy them.
TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


@dataclass(frozen=True)
class SchemaResult:
    """One response checked against `output_schema`: its parsed value, or why it failed."""

    value: Any
    error: str | None

    @property
    def valid(self) -> bool:
        return self.error is None


def check(text: str | None, schema: dict[str, Any]) -> SchemaResult:
    """Parse `text` as JSON and validate it; text that is not JSON fails the schema."""
    if text is None:
        return SchemaResult(None, "No response to validate")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return SchemaResult(None, f"Response is not valid JSON: {exc.msg}")

    error = validate(value, schema, path="")
    return SchemaResult(None if error else value, error)


def validate(value: Any, schema: dict[str, Any], path: str) -> str | None:
    """The first constraint `value` breaks, or None when it satisfies `schema`."""
    for rule in (_type, _enum, _bounds, _length, _pattern):
        error = rule(value, schema, path)
        if error:
            return error
    if isinstance(value, dict):
        return _properties(value, schema, path)
    if isinstance(value, list):
        return _items(value, schema, path)
    return None


def _type(value: Any, schema: dict[str, Any], path: str) -> str | None:
    expected = schema.get("type")
    if expected is None or _is_type(value, expected):
        return None
    return f"Expected {expected} at {_where(path)}, got {_type_name(value)}"


def _enum(value: Any, schema: dict[str, Any], path: str) -> str | None:
    allowed = schema.get("enum")
    if allowed is None or value in allowed:
        return None
    return f"Value at {_where(path)} is not one of {allowed}"


def _bounds(value: Any, schema: dict[str, Any], path: str) -> str | None:
    """`minimum` and `maximum`, which constrain numbers only."""
    if not _is_type(value, "number"):
        return None
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    if minimum is not None and value < minimum:
        return f"Value at {_where(path)} must be >= {minimum}"
    if maximum is not None and value > maximum:
        return f"Value at {_where(path)} must be <= {maximum}"
    return None


def _length(value: Any, schema: dict[str, Any], path: str) -> str | None:
    """`minLength` and `maxLength`, which constrain strings only."""
    if not isinstance(value, str):
        return None
    minimum, maximum = schema.get("minLength"), schema.get("maxLength")
    if minimum is not None and len(value) < minimum:
        return f"Value at {_where(path)} must be at least {minimum} characters"
    if maximum is not None and len(value) > maximum:
        return f"Value at {_where(path)} must be at most {maximum} characters"
    return None


def _pattern(value: Any, schema: dict[str, Any], path: str) -> str | None:
    pattern = schema.get("pattern")
    if pattern is None or not isinstance(value, str) or re.search(pattern, value):
        return None
    return f"Value at {_where(path)} does not match {pattern!r}"


def _properties(value: dict[str, Any], schema: dict[str, Any], path: str) -> str | None:
    """The `required` fields of an object and the subschema of each property present."""
    for name in schema.get("required") or ():
        if name not in value:
            return f"Missing required field: {_join(path, name)}"

    for name, subschema in (schema.get("properties") or {}).items():
        if name in value:
            error = validate(value[name], subschema, _join(path, name))
            if error:
                return error
    return None


def _items(value: list[Any], schema: dict[str, Any], path: str) -> str | None:
    """The subschema every element of an array must satisfy."""
    subschema = schema.get("items")
    if subschema is None:
        return None
    for index, element in enumerate(value):
        error = validate(element, subschema, f"{path}[{index}]")
        if error:
            return error
    return None


def _is_type(value: Any, expected: str) -> bool:
    """JSON Schema typing, where a boolean is not a number however Python stores it."""
    if isinstance(value, bool):
        return expected == "boolean"
    return isinstance(value, TYPES.get(expected, ()))


def _type_name(value: Any) -> str:
    """The JSON type name of a value, for the message a type mismatch produces."""
    return next((name for name in TYPES if _is_type(value, name)), "unknown")


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _where(path: str) -> str:
    return f"'{path}'" if path else "the response"

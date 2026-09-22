"""The JSON Schema draft 7 subset an `output_schema` may use."""

from __future__ import annotations

import json
import re

JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}
ROOT = "the response"


def parse_document(text: str | None, schema: dict) -> tuple[object, str | None]:
    """Parse a model response as JSON and validate it against `schema`.

    Returns the parsed document and `None`, or `None` and a human-readable
    message; unparsable JSON is reported as a validation failure too.
    """
    if text is None:
        return None, "Response is empty"
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Response is not valid JSON: {exc.msg}"

    error = validate_document(document, schema)
    return (None, error) if error else (document, None)


def validate_document(value, schema: dict, path: str = "") -> str | None:
    """The first validation error in `value`, or None when it satisfies `schema`."""
    expected = schema.get("type")
    if expected is not None and not _has_type(value, expected):
        return f"Expected {_name_of(expected)} at {path or ROOT}, got {_type_name(value)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"Value at {path or ROOT} is not one of the allowed values"

    if isinstance(value, dict):
        return _check_object(value, schema, path)
    if isinstance(value, list):
        return _check_items(value, schema, path)
    return _check_scalar(value, schema, path or ROOT)


def _check_object(value: dict, schema: dict, path: str) -> str | None:
    """`required` names must be present and `properties` must themselves hold."""
    for name in schema.get("required") or ():
        if name not in value:
            return f"Missing required field: {_join(path, name)}"

    for name, subschema in (schema.get("properties") or {}).items():
        error = validate_document(value[name], subschema, _join(path, name)) if name in value else None
        if error:
            return error
    return None


def _check_items(value: list, schema: dict, path: str) -> str | None:
    """Every element of an array is validated against the same `items` schema."""
    subschema = schema.get("items")
    if not isinstance(subschema, dict):
        return None

    for index, item in enumerate(value):
        error = validate_document(item, subschema, f"{path or ROOT}[{index}]")
        if error:
            return error
    return None


def _check_scalar(value, schema: dict, where: str) -> str | None:
    """Numeric bounds and string bounds, each ignored for other value kinds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"Value at {where} is less than the minimum {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"Value at {where} is greater than the maximum {schema['maximum']}"

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return f"Value at {where} is shorter than the minimum length {schema['minLength']}"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"Value at {where} is longer than the maximum length {schema['maxLength']}"
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return f"Value at {where} does not match pattern {schema['pattern']!r}"
    return None


def _has_type(value, expected) -> bool:
    """Draft 7 `type`, which may name one type or a list of them."""
    names = expected if isinstance(expected, list) else [expected]
    return any(_is_type(value, name) for name in names)


def _is_type(value, name: str) -> bool:
    if isinstance(value, bool) and name in ("integer", "number"):
        return False
    return isinstance(value, JSON_TYPES.get(name, object))


def _type_name(value) -> str:
    """What the value's JSON type is called, for the error message."""
    for name, python_type in JSON_TYPES.items():
        if name != "number" and _is_type(value, name):
            return name
    return "number"


def _name_of(expected) -> str:
    return " or ".join(expected) if isinstance(expected, list) else expected


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name

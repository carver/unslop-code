"""The JSON Schema draft 7 subset used to validate structured output.

Only the keywords the spec lists are implemented, with draft 7's rule that a
keyword constrains nothing when the value is of another kind. Validation stops
at the first broken rule and describes it in one human-readable sentence.
"""

from __future__ import annotations

import json
import re

TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float))
    and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}
TYPE_NAMES = {
    dict: "object",
    list: "array",
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    type(None): "null",
}


def parse_and_validate(text: str, schema: dict) -> tuple[object, str | None]:
    """Read `text` as JSON and check it against `schema`.

    Returns the parsed value and `None`, or `None` and the message describing
    why the response is not acceptable structured output.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc.msg}"
    error = validate(value, schema, "")
    return (None, error) if error else (value, None)


def validate(value, schema: dict, path: str) -> str | None:
    """The first rule `value` breaks under `schema`, described in words."""
    for rule in (_type, _enum, _bounds, _length, _pattern, _members, _elements):
        error = rule(value, schema, path)
        if error is not None:
            return error
    return None


def _type(value, schema: dict, path: str) -> str | None:
    check = TYPE_CHECKS.get(schema.get("type"))
    if check is None or check(value):
        return None
    expected = schema["type"]
    return f"Expected type {expected}{_at(path)}, got {_name(value)}"


def _enum(value, schema: dict, path: str) -> str | None:
    allowed = schema.get("enum")
    if allowed is None or value in allowed:
        return None
    return f"Value {value!r}{_at(path)} is not one of {allowed}"


def _bounds(value, schema: dict, path: str) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    if minimum is not None and value < minimum:
        return f"Value {value}{_at(path)} is less than minimum {minimum}"
    if maximum is not None and value > maximum:
        return f"Value {value}{_at(path)} is greater than maximum {maximum}"
    return None


def _length(value, schema: dict, path: str) -> str | None:
    if not isinstance(value, str):
        return None
    shortest, longest = schema.get("minLength"), schema.get("maxLength")
    if shortest is not None and len(value) < shortest:
        return f"String{_at(path)} is shorter than minLength {shortest}"
    if longest is not None and len(value) > longest:
        return f"String{_at(path)} is longer than maxLength {longest}"
    return None


def _pattern(value, schema: dict, path: str) -> str | None:
    pattern = schema.get("pattern")
    if pattern is None or not isinstance(value, str) or re.search(pattern, value):
        return None
    return f"String{_at(path)} does not match pattern {pattern}"


def _members(value, schema: dict, path: str) -> str | None:
    """`required` and `properties`, which only constrain objects."""
    if not isinstance(value, dict):
        return None
    for name in schema.get("required", []):
        if name not in value:
            return f"Missing required field: {_join(path, name)}"
    for name, subschema in (schema.get("properties") or {}).items():
        if name in value:
            error = validate(value[name], subschema, _join(path, name))
            if error is not None:
                return error
    return None


def _elements(value, schema: dict, path: str) -> str | None:
    """`items`, which validates every element of an array."""
    items = schema.get("items")
    if items is None or not isinstance(value, list):
        return None
    for index, element in enumerate(value):
        error = validate(element, items, f"{path}[{index}]")
        if error is not None:
            return error
    return None


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _at(path: str) -> str:
    return f" at {path!r}" if path else ""


def _name(value) -> str:
    return TYPE_NAMES.get(type(value), type(value).__name__)

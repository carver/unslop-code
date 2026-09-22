"""The JSON Schema draft-7 subset `output_schema` may use.

`validate` returns `None` when a value conforms and a human-readable message
naming the first problem when it does not. Draft 7 ignores keywords that do
not apply to the instance's type, so each check is a no-op for other types.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

# JSON Schema type names, and how each is recognised in Python. Booleans are
# checked before numbers because `bool` is a subclass of `int`.
TYPES = {
    "null": lambda value: value is None,
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "string": lambda value: isinstance(value, str),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def parse_and_validate(text: str, schema: Mapping[str, Any]) -> tuple[Any, str | None]:
    """Parse a model response as JSON and validate it; unparsable is invalid."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return None, f"Response is not valid JSON: {error.msg} (line {error.lineno})"
    return value, validate(value, schema)


def validate(value: Any, schema: Mapping[str, Any], path: str = "") -> str | None:
    """The first way `value` violates `schema`, or `None` if it conforms."""
    for keyword, expected in schema.items():
        check = _CHECKS.get(keyword)
        problem = check(value, expected, path) if check else None
        if problem is not None:
            return problem
    return None


def _at(path: str) -> str:
    """The `field 'a.b': ` prefix an error carries, empty at the root."""
    return f"Field '{path}': " if path else ""


def _type_name(value: Any) -> str:
    return next((name for name, matches in TYPES.items() if matches(value)), "unknown")


def _check_type(value: Any, expected: Any, path: str) -> str | None:
    names = expected if isinstance(expected, list) else [expected]
    if any(TYPES[name](value) for name in names if name in TYPES):
        return None
    return f"{_at(path) or 'Value '}expected type {' or '.join(names)}, got {_type_name(value)}"


def _check_required(value: Any, expected: Any, path: str) -> str | None:
    if not isinstance(value, dict):
        return None
    missing = next((name for name in expected if name not in value), None)
    return None if missing is None else f"Missing required field: {_join(path, missing)}"


def _check_properties(value: Any, expected: Any, path: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for name, subschema in expected.items():
        if name in value:
            problem = validate(value[name], subschema, _join(path, name))
            if problem is not None:
                return problem
    return None


def _check_items(value: Any, expected: Any, path: str) -> str | None:
    if not isinstance(value, list):
        return None
    for index, item in enumerate(value):
        problem = validate(item, expected, f"{path}[{index}]" if path else f"[{index}]")
        if problem is not None:
            return problem
    return None


def _check_enum(value: Any, expected: Any, path: str) -> str | None:
    if value in expected:
        return None
    return f"{_at(path) or 'Value '}{value!r} is not one of {expected}"


def _check_minimum(value: Any, expected: Any, path: str) -> str | None:
    if not TYPES["number"](value) or value >= expected:
        return None
    return f"{_at(path) or 'Value '}{value} is below the minimum {expected}"


def _check_maximum(value: Any, expected: Any, path: str) -> str | None:
    if not TYPES["number"](value) or value <= expected:
        return None
    return f"{_at(path) or 'Value '}{value} is above the maximum {expected}"


def _check_min_length(value: Any, expected: Any, path: str) -> str | None:
    if not isinstance(value, str) or len(value) >= expected:
        return None
    return f"{_at(path) or 'Value '}is shorter than minLength {expected}"


def _check_max_length(value: Any, expected: Any, path: str) -> str | None:
    if not isinstance(value, str) or len(value) <= expected:
        return None
    return f"{_at(path) or 'Value '}is longer than maxLength {expected}"


def _check_pattern(value: Any, expected: Any, path: str) -> str | None:
    if not isinstance(value, str) or re.search(expected, value):
        return None
    return f"{_at(path) or 'Value '}does not match pattern '{expected}'"


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


_CHECKS = {
    "type": _check_type,
    "required": _check_required,
    "properties": _check_properties,
    "items": _check_items,
    "enum": _check_enum,
    "minimum": _check_minimum,
    "maximum": _check_maximum,
    "minLength": _check_min_length,
    "maxLength": _check_max_length,
    "pattern": _check_pattern,
}

"""Validating a response against a task's `output_schema`.

The supported JSON Schema draft 7 keywords are `type`, `required`,
`properties`, `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`
and `pattern`. A keyword that cannot apply to the value it meets is ignored, as
draft 7 requires: `minLength` says nothing about a number.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

#: JSON type names and the Python type each one accepts.
_JSON_TYPES = {
    "null": type(None),
    "boolean": bool,
    "integer": int,
    "number": float,
    "string": str,
    "array": list,
    "object": dict,
}


@dataclass(frozen=True)
class SchemaCheck:
    """The outcome of checking one response: its parsed value, or what went wrong."""

    value: Any = None
    error: str | None = None


def check_output(schema: dict[str, Any], text: str) -> SchemaCheck:
    """Parse `text` as JSON and validate it against `schema`.

    A response that is not JSON at all fails the same way as one that parses but
    does not match the schema.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return SchemaCheck(error=f"Invalid JSON: {exc.msg} (line {exc.lineno})")
    error = validate(schema, value)
    return SchemaCheck(error=error) if error else SchemaCheck(value=value)


def validate(schema: dict[str, Any], value: Any, path: str = "") -> str | None:
    """The first rule `value` breaks, described for a human, or None if it holds.

    `path` names the part of the response under check, and is empty at its root.
    """
    for keyword, check in _CHECKS.items():
        error = check(schema[keyword], value, path) if keyword in schema else None
        if error is not None:
            return error
    return None


def _check_type(rule: Any, value: Any, path: str) -> str | None:
    """`type` accepts one name or a list of them."""
    names = rule if isinstance(rule, list) else [rule]
    if any(_is_type(name, value) for name in names):
        return None
    return _message(f"expected {' or '.join(names)}, got {_type_name(value)}", path)


def _check_required(rule: list[str], value: Any, path: str) -> str | None:
    if not isinstance(value, dict):
        return None
    missing = [name for name in rule if name not in value]
    return _message(f"missing required field: {missing[0]}", path) if missing else None


def _check_properties(rule: dict[str, Any], value: Any, path: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for name, subschema in rule.items():
        if name in value:
            error = validate(subschema, value[name], f"{path}.{name}" if path else name)
            if error is not None:
                return error
    return None


def _check_items(rule: dict[str, Any], value: Any, path: str) -> str | None:
    if not isinstance(value, list):
        return None
    for index, item in enumerate(value):
        error = validate(rule, item, f"{path}[{index}]")
        if error is not None:
            return error
    return None


def _check_enum(rule: list[Any], value: Any, path: str) -> str | None:
    if value in rule:
        return None
    return _message(f"{value!r} is not one of {rule}", path)


def _check_minimum(rule: float, value: Any, path: str) -> str | None:
    if not _is_number(value) or value >= rule:
        return None
    return _message(f"{value} is less than the minimum of {rule}", path)


def _check_maximum(rule: float, value: Any, path: str) -> str | None:
    if not _is_number(value) or value <= rule:
        return None
    return _message(f"{value} is greater than the maximum of {rule}", path)


def _check_min_length(rule: int, value: Any, path: str) -> str | None:
    if not isinstance(value, str) or len(value) >= rule:
        return None
    return _message(f"length {len(value)} is below the minimum of {rule}", path)


def _check_max_length(rule: int, value: Any, path: str) -> str | None:
    if not isinstance(value, str) or len(value) <= rule:
        return None
    return _message(f"length {len(value)} is above the maximum of {rule}", path)


def _check_pattern(rule: str, value: Any, path: str) -> str | None:
    if not isinstance(value, str) or re.search(rule, value):
        return None
    return _message(f"{value!r} does not match pattern {rule!r}", path)


#: Keywords in the order they are checked, so the message a failure gets is the
#: most specific one: a wrong type is reported before the fields it lacks.
_CHECKS: dict[str, Callable[[Any, Any, str], str | None]] = {
    "type": _check_type,
    "enum": _check_enum,
    "required": _check_required,
    "properties": _check_properties,
    "items": _check_items,
    "minimum": _check_minimum,
    "maximum": _check_maximum,
    "minLength": _check_min_length,
    "maxLength": _check_max_length,
    "pattern": _check_pattern,
}


def _message(problem: str, path: str) -> str:
    """Name the failing field, unless the whole response is what failed."""
    if not path:
        return problem[0].upper() + problem[1:]
    return f"Field '{path}': {problem}"


def _is_type(name: str, value: Any) -> bool:
    """Whether a value has a JSON type; a boolean is never a number."""
    if isinstance(value, bool):
        return name == "boolean"
    if name == "number":
        return _is_number(value)
    return isinstance(value, _JSON_TYPES[name])


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_name(value: Any) -> str:
    return next(name for name in _JSON_TYPES if _is_type(name, value))

"""JSON Schema (draft 7) validation of structured responses.

A task with an `output_schema` expects the model to answer with JSON. The
response is parsed first, then checked against the keywords the schema uses:
`type`, `required`, `properties`, `items`, `enum`, `minimum`, `maximum`,
`minLength`, `maxLength` and `pattern`. Text that is not JSON at all fails the
same way a badly shaped object does.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from errors import UsageError

# JSON type names, paired with what they are in Python. `bool` comes before
# `int` so that `true` is a boolean rather than the integer 1.
_KINDS = (
    (dict, "object"),
    (list, "array"),
    (str, "string"),
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (type(None), "null"),
)
TYPE_NAMES = tuple(name for _, name in _KINDS)


@dataclass(frozen=True)
class Structured:
    """A response parsed as JSON and checked against a schema.

    `error` is None when the value satisfies the schema, and a human readable
    account of the first broken rule otherwise.
    """

    value: Any
    error: str | None


def check_output(schema: dict | None, text: str) -> Structured | None:
    """Parse and validate one response; None when the task declares no schema."""
    if schema is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return Structured(None, f"Invalid JSON: {error.msg}")
    return Structured(value, validate(value, schema, ""))


def validate(value: Any, schema: dict, where: str) -> str | None:
    """The first rule `value` breaks, or None when it satisfies the schema.

    `where` names the value inside the response, so nested failures point at the
    field that caused them.
    """
    for keyword, rule in _RULES.items():
        if keyword in schema:
            error = rule(value, schema[keyword], where)
            if error is not None:
                return error
    return None


def check_schema(schema: dict, where: str) -> None:
    """Fail fast on a configured schema the validator cannot apply."""
    kind = schema.get("type")
    if kind is not None and kind not in TYPE_NAMES:
        raise UsageError(f"{where}.type must be one of {', '.join(TYPE_NAMES)}; got '{kind}'")
    if schema.get("pattern") is not None:
        _compile(str(schema["pattern"]), where)

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise UsageError(f"{where}.properties must be a mapping")
    for name, subschema in properties.items():
        _check_subschema(subschema, f"{where}.properties.{name}")
    if schema.get("items") is not None:
        _check_subschema(schema["items"], f"{where}.items")


def _check_subschema(schema: Any, where: str) -> None:
    if not isinstance(schema, dict):
        raise UsageError(f"{where} must be a mapping")
    check_schema(schema, where)


def _compile(pattern: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as error:
        raise UsageError(f"{where}.pattern is not a valid regex: {error}") from None


def _kind(value: Any) -> str:
    """The JSON type name of a value."""
    return next(name for python, name in _KINDS if isinstance(value, python))


def _name(where: str) -> str:
    """How a value is referred to in an error message."""
    return where or "value"


def _type(value: Any, expected: str, where: str) -> str | None:
    kind = _kind(value)
    # Every integer is also a number, which is the one widening draft 7 allows.
    if kind == expected or (expected == "number" and kind == "integer"):
        return None
    return f"{_name(where)}: expected {expected}, got {kind}"


def _required(value: Any, expected: list, where: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in expected:
        if key not in value:
            return f"Missing required field: {key if not where else f'{where}.{key}'}"
    return None


def _properties(value: Any, expected: dict, where: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for key, subschema in expected.items():
        if key in value:
            error = validate(value[key], subschema, f"{where}.{key}" if where else key)
            if error is not None:
                return error
    return None


def _items(value: Any, expected: dict, where: str) -> str | None:
    if not isinstance(value, list):
        return None
    for index, element in enumerate(value):
        error = validate(element, expected, f"{_name(where)}[{index}]")
        if error is not None:
            return error
    return None


def _enum(value: Any, expected: list, where: str) -> str | None:
    if value in expected:
        return None
    return f"{_name(where)}: {json.dumps(value)} is not one of {json.dumps(expected)}"


def _numeric(value: Any) -> bool:
    """Whether a bound applies: booleans are not numbers, whatever Python thinks."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _minimum(value: Any, expected: float, where: str) -> str | None:
    if _numeric(value) and value < expected:
        return f"{_name(where)}: {value} is less than the minimum {expected}"
    return None


def _maximum(value: Any, expected: float, where: str) -> str | None:
    if _numeric(value) and value > expected:
        return f"{_name(where)}: {value} is greater than the maximum {expected}"
    return None


def _min_length(value: Any, expected: int, where: str) -> str | None:
    if isinstance(value, str) and len(value) < expected:
        return f"{_name(where)}: shorter than the minimum length {expected}"
    return None


def _max_length(value: Any, expected: int, where: str) -> str | None:
    if isinstance(value, str) and len(value) > expected:
        return f"{_name(where)}: longer than the maximum length {expected}"
    return None


def _pattern(value: Any, expected: str, where: str) -> str | None:
    if isinstance(value, str) and re.search(expected, value) is None:
        return f"{_name(where)}: does not match pattern {expected}"
    return None


# Checked in this order, so the broadest failure is the one reported.
_RULES = {
    "type": _type,
    "required": _required,
    "enum": _enum,
    "minimum": _minimum,
    "maximum": _maximum,
    "minLength": _min_length,
    "maxLength": _max_length,
    "pattern": _pattern,
    "properties": _properties,
    "items": _items,
}

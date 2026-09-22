"""Validation of a response against a task's ``output_schema``.

The supported keywords are the JSON Schema draft 7 subset a generation task
needs: ``type``, ``required``, ``properties``, ``items``, ``enum``,
``minimum``, ``maximum``, ``minLength``, ``maxLength``, and ``pattern``.
Failures are reported as one human-readable message naming the field at fault.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from errors import ConfigError

#: A schema is the raw mapping the config declared, kept as plain JSON Schema.
Schema = dict[str, Any]

#: JSON Schema type names and the Python types that satisfy them, most specific first
#: so that naming the type of a value reports ``integer`` rather than ``number``.
TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


@dataclass(frozen=True)
class SchemaCheck:
    """The value a response contributes, and why it was rejected if it was.

    ``value`` is the parsed JSON document when the schema is satisfied, the raw
    response text when the task declares no schema, and ``None`` otherwise.
    """

    value: Any
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None


def build_schema(raw: Any, label: str) -> Schema | None:
    """Validate the optional ``output_schema`` block: a mapping whose patterns compile."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{label}.output_schema must be a mapping")
    _check_patterns(raw, f"{label}.output_schema")
    return raw


def check_output(schema: Schema | None, text: str) -> SchemaCheck:
    """Parse ``text`` as JSON and validate it, or pass it through when there is no schema."""
    if schema is None:
        return SchemaCheck(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return SchemaCheck(None, f"Response is not valid JSON: {exc.msg} (line {exc.lineno})")
    error = validate(schema, value, "response")
    return SchemaCheck(None, error) if error else SchemaCheck(value)


def validate(schema: Schema, value: Any, field: str) -> str | None:
    """Check one value against one schema, returning the first failure found."""
    for keyword, check in _KEYWORDS.items():
        if keyword in schema:
            error = check(schema[keyword], value, field)
            if error is not None:
                return error
    return None


def _check_type(expected: Any, value: Any, field: str) -> str | None:
    allowed = TYPES.get(expected)
    if allowed is None or isinstance(value, allowed) and not _mistyped_boolean(expected, value):
        return None
    return f"Field {field} must be of type {expected}, got {_type_name(value)}"


def _mistyped_boolean(expected: str, value: Any) -> bool:
    """``True`` passes ``isinstance(value, int)``, but JSON numbers are not booleans."""
    return isinstance(value, bool) and expected != "boolean"


def _check_required(names: Any, value: Any, field: str) -> str | None:
    if not isinstance(value, dict):
        return None
    missing = [name for name in names if name not in value]
    if missing:
        return f"Missing required field: {missing[0]}"
    return None


def _check_properties(properties: Any, value: Any, field: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for name, subschema in properties.items():
        if name in value:
            error = validate(subschema, value[name], name)
            if error is not None:
                return error
    return None


def _check_items(items: Any, value: Any, field: str) -> str | None:
    if not isinstance(value, list):
        return None
    for index, item in enumerate(value):
        error = validate(items, item, f"{field}[{index}]")
        if error is not None:
            return error
    return None


def _check_enum(allowed: Any, value: Any, field: str) -> str | None:
    if value in allowed:
        return None
    return f"Field {field} must be one of: {', '.join(json.dumps(item) for item in allowed)}"


def _check_minimum(limit: Any, value: Any, field: str) -> str | None:
    if not _is_number(value) or value >= limit:
        return None
    return f"Field {field} must be at least {limit}"


def _check_maximum(limit: Any, value: Any, field: str) -> str | None:
    if not _is_number(value) or value <= limit:
        return None
    return f"Field {field} must be at most {limit}"


def _check_min_length(limit: Any, value: Any, field: str) -> str | None:
    if not isinstance(value, str) or len(value) >= limit:
        return None
    return f"Field {field} must be at least {limit} characters long"


def _check_max_length(limit: Any, value: Any, field: str) -> str | None:
    if not isinstance(value, str) or len(value) <= limit:
        return None
    return f"Field {field} must be at most {limit} characters long"


def _check_pattern(pattern: Any, value: Any, field: str) -> str | None:
    if not isinstance(value, str) or re.search(pattern, value):
        return None
    return f"Field {field} must match pattern {pattern}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _type_name(value: Any) -> str:
    """The JSON Schema name of a value's type, for the type mismatch message."""
    for name, types in TYPES.items():
        if isinstance(value, types) and not _mistyped_boolean(name, value):
            return name
    return type(value).__name__


def _check_patterns(schema: Mapping[str, Any], label: str) -> None:
    """Compile every ``pattern`` in a schema so a bad one is reported before the run."""
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{label}.pattern is not a valid regular expression: {exc}") from exc
    for name, subschema in (schema.get("properties") or {}).items():
        if isinstance(subschema, dict):
            _check_patterns(subschema, f"{label}.properties.{name}")
    items = schema.get("items")
    if isinstance(items, dict):
        _check_patterns(items, f"{label}.items")


#: Keyword checks in the order they run, so a type mismatch is reported before its details.
_KEYWORDS: dict[str, Callable[[Any, Any, str], str | None]] = {
    "type": _check_type,
    "required": _check_required,
    "enum": _check_enum,
    "minimum": _check_minimum,
    "maximum": _check_maximum,
    "minLength": _check_min_length,
    "maxLength": _check_max_length,
    "pattern": _check_pattern,
    "properties": _check_properties,
    "items": _check_items,
}

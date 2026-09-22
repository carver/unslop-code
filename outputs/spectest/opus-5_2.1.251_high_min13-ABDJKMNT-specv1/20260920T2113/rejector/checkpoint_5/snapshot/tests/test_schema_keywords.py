"""The draft 7 keywords `output_schema` validation supports."""

from __future__ import annotations

import json

import pytest

from rejlib.schema import check_response, validate


def check(schema: dict, value) -> str | None:
    """The validation error for an already-parsed value, or ``None``."""
    return validate(schema, value)


# "support JSON Schema draft 7 rules for `type`"
@pytest.mark.parametrize("kind,value", [
    ("object", {}), ("array", []), ("string", "x"), ("number", 1.5), ("integer", 3),
    ("boolean", True), ("null", None),
])
def test_type_accepts_matching_values(kind, value):
    assert check({"type": kind}, value) is None


# "support JSON Schema draft 7 rules for `type`"
@pytest.mark.parametrize("kind,value", [
    ("object", []), ("array", {}), ("string", 1), ("number", "1"), ("integer", 1.5),
    ("boolean", "true"), ("null", 0),
])
def test_type_rejects_other_values(kind, value):
    assert check({"type": kind}, value) is not None


# "support JSON Schema draft 7 rules for ... `required`"
def test_required_reports_the_missing_field():
    error = check({"type": "object", "required": ["code", "explanation"]}, {"code": "x"})
    assert error == "Missing required field: explanation"


# "support JSON Schema draft 7 rules for ... `properties`"
def test_properties_validate_each_present_value():
    schema = {"type": "object", "properties": {"code": {"type": "string"}}}
    assert check(schema, {"code": "def f(): pass"}) is None
    assert "code" in check(schema, {"code": 7})


# "support JSON Schema draft 7 rules for ... `properties`" - nested objects too
def test_properties_nest():
    schema = {
        "type": "object",
        "properties": {"meta": {"type": "object", "required": ["id"]}},
    }
    assert check(schema, {"meta": {"id": 1}}) is None
    assert check(schema, {"meta": {}}) == "Missing required field: meta.id"


# "support JSON Schema draft 7 rules for ... `items`"
def test_items_validate_every_element():
    schema = {"type": "array", "items": {"type": "integer"}}
    assert check(schema, [1, 2, 3]) is None
    assert check(schema, [1, "two"]) is not None


# "support JSON Schema draft 7 rules for ... `enum`"
def test_enum_restricts_the_value():
    schema = {"type": "string", "enum": ["a", "b"]}
    assert check(schema, "a") is None
    assert check(schema, "c") is not None


# "support JSON Schema draft 7 rules for ... `minimum`, `maximum`"
@pytest.mark.parametrize("value,valid", [(0, False), (1, True), (5, True), (6, False)])
def test_minimum_and_maximum_bound_numbers(value, valid):
    schema = {"type": "integer", "minimum": 1, "maximum": 5}
    assert (check(schema, value) is None) is valid


# "support JSON Schema draft 7 rules for ... `minLength`, `maxLength`"
@pytest.mark.parametrize("value,valid", [("", False), ("ab", True), ("abcd", False)])
def test_length_bounds_strings(value, valid):
    schema = {"type": "string", "minLength": 1, "maxLength": 3}
    assert (check(schema, value) is None) is valid


# "support JSON Schema draft 7 rules for ... `pattern`"
def test_pattern_matches_strings():
    schema = {"type": "string", "pattern": "^[0-9]+$"}
    assert check(schema, "123") is None
    assert check(schema, "12a") is not None


# "when `output_schema` is present, parse the model response as JSON"
def test_valid_json_is_parsed_into_the_check():
    check = check_response({"type": "object"}, json.dumps({"code": "x"}))
    assert check.valid is True
    assert check.value == {"code": "x"}


# "invalid JSON also counts as a schema failure"
@pytest.mark.parametrize("text", ["not json", "{unclosed", "", "{'single': 'quotes'}"])
def test_invalid_json_is_a_schema_failure(text):
    result = check_response({"type": "object"}, text)
    assert result.valid is False
    assert result.error


# "`result.schema_error` to a human-readable validation message"
def test_error_names_the_offending_field():
    result = check_response(
        {"type": "object", "properties": {"n": {"type": "integer"}}}, '{"n": "x"}'
    )
    assert "n" in result.error and "integer" in result.error

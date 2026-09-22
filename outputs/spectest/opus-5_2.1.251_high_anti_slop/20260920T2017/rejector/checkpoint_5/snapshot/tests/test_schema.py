"""Structured output validation against the supported draft 7 keywords."""

import json

import pytest

from schema import SchemaCheck, check_output, validate

OBJECT_SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}


def check(schema, value):
    return check_output(schema, json.dumps(value))


def test_a_matching_object_is_returned_parsed():
    payload = {"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}
    assert check(OBJECT_SCHEMA, payload) == SchemaCheck(value=payload)


def test_a_missing_required_field_is_named():
    assert check(OBJECT_SCHEMA, {"code": "x"}).error == "Missing required field: explanation"


def test_a_field_of_the_wrong_type_is_named():
    error = check(OBJECT_SCHEMA, {"code": 1, "explanation": "y"}).error
    assert error == "Field 'code': expected string, got integer"


def test_text_that_is_not_json_fails_as_a_schema_failure():
    assert check_output(OBJECT_SCHEMA, "Here you go: def add(a, b)").error.startswith("Invalid JSON")


def test_the_response_type_itself_is_checked():
    assert check(OBJECT_SCHEMA, ["code"]).error == "Expected object, got array"


def test_a_type_may_list_alternatives():
    assert validate({"type": ["string", "null"]}, None) is None


def test_a_boolean_is_not_an_integer():
    assert validate({"type": "integer"}, True) == "Expected integer, got boolean"


def test_an_integer_satisfies_number():
    assert validate({"type": "number"}, 7) is None


def test_items_are_validated_and_located():
    schema = {"type": "array", "items": {"type": "integer", "minimum": 2}}
    assert validate(schema, [4, 1]) == "Field '[1]': 1 is less than the minimum of 2"


def test_nested_properties_report_their_path():
    schema = {"properties": {"meta": {"properties": {"lang": {"enum": ["py", "js"]}}}}}
    error = validate(schema, {"meta": {"lang": "rb"}})
    assert error == "Field 'meta.lang': 'rb' is not one of ['py', 'js']"


@pytest.mark.parametrize(
    "schema, value, expected",
    [
        ({"maximum": 10}, 11, "11 is greater than the maximum of 10"),
        ({"minLength": 3}, "ab", "Length 2 is below the minimum of 3"),
        ({"maxLength": 1}, "ab", "Length 2 is above the maximum of 1"),
        ({"pattern": r"^\d+$"}, "12a", "'12a' does not match pattern '^\\\\d+$'"),
    ],
)
def test_the_remaining_keywords_report_what_failed(schema, value, expected):
    assert validate(schema, value) == expected


@pytest.mark.parametrize(
    "schema, value",
    [
        ({"minLength": 5}, 3),
        ({"minimum": 5}, "text"),
        ({"pattern": "^a"}, 42),
        ({"required": ["a"]}, ["a"]),
    ],
)
def test_a_keyword_that_cannot_apply_is_ignored(schema, value):
    assert validate(schema, value) is None

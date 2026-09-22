"""Draft 7 validation of a structured response."""

import pytest

from schema import check

OBJECT = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}


def test_a_valid_response_is_parsed_into_its_value():
    result = check('{"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}', OBJECT)
    assert result.valid
    assert result.value == {"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}


def test_a_missing_required_field_is_named():
    result = check('{"code": "x"}', OBJECT)
    assert (result.value, result.error) == (None, "Missing required field: explanation")


def test_text_that_is_not_json_fails_the_schema():
    assert check("Here is the code!", OBJECT).error.startswith("Response is not valid JSON")


def test_a_loop_without_an_answer_fails_the_schema():
    assert check(None, OBJECT).error == "No response to validate"


@pytest.mark.parametrize(
    ("text", "schema", "message"),
    [
        ('{"code": 1}', {"properties": {"code": {"type": "string"}}}, "Expected string at 'code', got number"),
        ("[1, 2]", {"type": "object"}, "Expected object at the response, got array"),
        ('"gold"', {"enum": ["red", "blue"]}, "Value at the response is not one of ['red', 'blue']"),
        ("3", {"minimum": 5}, "Value at the response must be >= 5"),
        ("9", {"maximum": 5}, "Value at the response must be <= 5"),
        ('"ab"', {"minLength": 3}, "Value at the response must be at least 3 characters"),
        ('"abcd"', {"maxLength": 3}, "Value at the response must be at most 3 characters"),
        ('"nope"', {"pattern": "^ok"}, "Value at the response does not match '^ok'"),
        ('{"tags": ["a", 2]}', {"properties": {"tags": {"items": {"type": "string"}}}},
         "Expected string at 'tags[1]', got number"),
    ],
)
def test_each_keyword_reports_what_it_rejected(text, schema, message):
    assert check(text, schema).error == message


def test_a_boolean_is_not_a_number():
    assert check("true", {"type": "number"}).error == "Expected number at the response, got boolean"
    assert check("true", {"type": "boolean"}).valid


def test_nested_objects_are_validated_through_their_path():
    schema = {"properties": {"result": {"type": "object", "required": ["score"]}}}
    assert check('{"result": {}}', schema).error == "Missing required field: result.score"


def test_properties_that_are_absent_are_not_checked():
    assert check('{"code": "x"}', {"properties": {"explanation": {"type": "string"}}}).valid

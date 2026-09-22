"""Structured output: JSON Schema validation of responses."""

import json

import pytest

from errors import UsageError
from schema import check_output, check_schema, validate

SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}

TASK = {
    "name": "code_gen",
    "model": "gpt-4",
    "prompt": {"user": "{problem}"},
    "generation": {"scheme": "greedy", "max_tokens": 64},
    "output_field": "code",
    "output_schema": SCHEMA,
}

ANSWER = {"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}
ROWS = [{"problem": "add two numbers"}]


def errors_of(value, schema=None):
    return validate(value, schema or SCHEMA, "")


def test_a_matching_object_validates():
    assert errors_of(ANSWER) is None


def test_a_missing_required_field_is_named():
    assert errors_of({"code": "x"}) == "Missing required field: explanation"


def test_a_wrong_field_type_is_named():
    assert errors_of({"code": 1, "explanation": "x"}) == "code: expected string, got integer"


def test_a_wrong_root_type_is_reported():
    assert errors_of([]) == "value: expected object, got array"


def test_nested_objects_report_their_path():
    schema = {"type": "object", "properties": {"outer": SCHEMA}}
    failure = errors_of({"outer": {"code": "x"}}, schema)

    assert failure == "Missing required field: outer.explanation"


def test_array_items_are_validated():
    schema = {"type": "array", "items": {"type": "integer"}}

    assert errors_of([1, 2], schema) is None
    assert errors_of([1, "two"], schema) == "value[1]: expected integer, got string"


def test_enum_bounds_and_lengths_are_enforced():
    assert errors_of("c", {"enum": ["a", "b"]}) == 'value: "c" is not one of ["a", "b"]'
    assert errors_of(3, {"minimum": 5}) == "value: 3 is less than the minimum 5"
    assert errors_of(9, {"maximum": 5}) == "value: 9 is greater than the maximum 5"
    assert errors_of("ab", {"minLength": 3}) == "value: shorter than the minimum length 3"
    assert errors_of("abcd", {"maxLength": 3}) == "value: longer than the maximum length 3"
    assert errors_of("abc", {"pattern": "^x"}) == "value: does not match pattern ^x"


def test_an_integer_satisfies_the_number_type():
    assert errors_of(3, {"type": "number"}) is None
    assert errors_of(True, {"type": "integer"}) == "value: expected integer, got boolean"


def test_text_that_is_not_json_fails_validation():
    structured = check_output(SCHEMA, "here you go: def add(a, b)")

    assert structured.value is None and "Invalid JSON" in structured.error


def test_a_task_without_a_schema_validates_nothing():
    assert check_output(None, "anything") is None


def test_a_valid_response_is_written_as_parsed_json(cli, api):
    url, _ = api(lambda payload, call: json.dumps(ANSWER))
    run = cli({**TASK, "api_url": url}, ROWS)

    assert run.records[0]["output"] == {"code": ANSWER}
    assert run.records[0]["result"]["passed"] is True
    assert run.records[0]["result"]["schema_valid"] is True
    assert run.summary["passed"] == 1


def test_an_invalid_response_fails_the_row(cli, api):
    url, _ = api(lambda payload, call: json.dumps({"code": "def add"}))
    run = cli({**TASK, "api_url": url}, ROWS)

    assert run.records[0]["output"] is None
    assert run.records[0]["result"]["passed"] is False
    assert run.records[0]["result"]["schema_valid"] is False
    assert run.records[0]["result"]["schema_error"] == "Missing required field: explanation"
    assert run.summary["failed"] == 1


def test_validation_runs_before_evaluation(cli, api):
    judge = {
        "type": "llm_judge",
        "judge_prompt": {"user": "Rate this:\n{__response__}\n\nScore:"},
        "threshold": 7,
        "extract": "first_number",
    }
    url, state = api(lambda payload, call: "not json at all")
    run = cli({**TASK, "api_url": url, "evaluation": judge}, ROWS)

    # The judge is never asked about a response that failed the schema.
    assert state.calls == [state.calls[0]]
    assert run.records[0]["result"]["schema_valid"] is False


def test_rejection_sampling_retries_a_response_that_fails_the_schema(cli, api):
    url, _ = api(lambda payload, call: "{}" if call == 1 else json.dumps(ANSWER))
    run = cli(
        {
            **TASK,
            "api_url": url,
            "generation": {"scheme": "rejection", "temperature": 0.7, "n": 3, "max_tokens": 64},
        },
        ROWS,
    )

    assert run.records[0]["result"]["attempts"] == 2
    assert run.records[0]["output"] == {"code": ANSWER}
    assert run.records[0]["result"]["schema_valid"] is True


def test_rejection_sampling_that_never_validates_writes_no_output(cli, api):
    url, _ = api(lambda payload, call: "{}")
    run = cli(
        {
            **TASK,
            "api_url": url,
            "generation": {"scheme": "rejection", "temperature": 0.7, "n": 2, "max_tokens": 64},
        },
        ROWS,
    )

    assert run.records[0]["output"] is None
    assert run.records[0]["result"] == {
        "passed": False,
        "extracted_answer": None,
        "attempts": 2,
        "schema_valid": False,
        "schema_error": "Missing required field: code",
    }


def test_multiple_solutions_keep_only_the_valid_responses(cli, api):
    url, _ = api(lambda payload, call: json.dumps(ANSWER) if call % 2 else "{}")
    run = cli(
        {
            **TASK,
            "api_url": url,
            "num_solutions": 2,
            "generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64},
        },
        ROWS,
    )

    assert run.records[0]["output"] == [{"code": ANSWER, "icl_setup": None}]
    assert run.records[0]["result"]["attempts"] == 2


def test_a_schema_the_validator_cannot_apply_is_rejected(cli, api):
    url, _ = api(lambda payload, call: "{}")
    run = cli({**TASK, "api_url": url, "output_schema": {"type": "mapping"}}, ROWS)

    assert run.code == 1
    assert "task.output_schema.type must be one of" in run.stderr


def test_a_bad_pattern_in_a_schema_is_rejected():
    with pytest.raises(UsageError, match="not a valid regex"):
        check_schema({"properties": {"code": {"pattern": "("}}}, "task.output_schema")

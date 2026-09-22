"""Structured output validation, both the validator itself and tasks that use it."""

import json

from output_schema import build_schema, check_output, validate

SCHEMA = """  output_schema:
    type: "object"
    required: ["code", "explanation"]
    properties:
      code:
        type: "string"
      explanation:
        type: "string"
"""

VALID = json.dumps({"code": "def add(a, b): return a + b", "explanation": "Simple addition"})
MISSING_FIELD = json.dumps({"code": "def add(a, b): return a + b"})


def schema_config(url, *, scheme="greedy", temperature=0.0, n=1, evaluation=""):
    """A task config that validates its responses against :data:`SCHEMA`."""
    return f"""
task:
  name: "structured"
  api_url: "{url}"
  model: "mock-model"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "{scheme}"
    temperature: {temperature}
    max_tokens: 64
    n: {n}
{evaluation}{SCHEMA}  output_field: "code"
"""


ROWS = [{"question": "write add"}]


def test_valid_response_is_stored_as_parsed_json(mock_server, run_cli):
    server = mock_server("--answer-only", "--answer", VALID)

    completed, summary, results = run_cli(schema_config(server.url), ROWS)

    assert completed.returncode == 0, completed.stderr
    assert results[0]["output"] == {"code": json.loads(VALID)}
    assert results[0]["result"]["passed"] is True
    assert results[0]["result"]["schema_valid"] is True
    assert "schema_error" not in results[0]["result"]
    assert summary["passed"] == 1


def test_missing_required_field_fails_the_row(mock_server, run_cli):
    server = mock_server("--answer-only", "--answer", MISSING_FIELD)

    completed, summary, results = run_cli(schema_config(server.url), ROWS)

    assert completed.returncode == 0, completed.stderr
    assert results[0]["output"] is None
    assert results[0]["result"]["passed"] is False
    assert results[0]["result"]["schema_valid"] is False
    assert results[0]["result"]["schema_error"] == "Missing required field: explanation"
    assert summary["failed"] == 1


def test_response_that_is_not_json_fails_the_row(mock_server, run_cli):
    server = mock_server("--answer-only", "--answer", "here you go: add(a, b)")

    completed, _, results = run_cli(schema_config(server.url), ROWS)

    assert completed.returncode == 0, completed.stderr
    assert results[0]["result"]["schema_valid"] is False
    assert "not valid JSON" in results[0]["result"]["schema_error"]


def test_rejection_retries_until_the_schema_is_satisfied(mock_server, run_cli):
    server = mock_server(
        "--answer-only", "--answer", VALID, "--wrong-answer", MISSING_FIELD, "--pass-after", "1"
    )
    config = schema_config(server.url, scheme="rejection", temperature=0.7, n=3)

    completed, summary, results = run_cli(config, ROWS)

    assert completed.returncode == 0, completed.stderr
    assert results[0]["result"]["attempts"] == 2
    assert results[0]["result"]["passed"] is True
    assert results[0]["output"] == {"code": json.loads(VALID)}
    assert summary["total_api_calls"] == 2


def test_evaluation_is_skipped_when_the_schema_fails(mock_server, run_cli):
    server = mock_server("--answer-only", "--answer", MISSING_FIELD)
    evaluation = '  evaluation:\n    type: "contains"\n    answer_field: "question"\n'
    config = schema_config(server.url, evaluation=evaluation)

    completed, _, results = run_cli(config, ROWS)

    assert completed.returncode == 0, completed.stderr
    assert results[0]["result"]["schema_valid"] is False
    assert results[0]["result"]["extracted_answer"] is None


def test_type_mismatch_names_the_offending_field():
    schema = {"type": "object", "properties": {"score": {"type": "number"}}}

    assert validate(schema, {"score": "high"}, "response") == (
        "Field score must be of type number, got string"
    )
    assert validate(schema, {"score": 4.5}, "response") is None


def test_draft_7_keywords_are_enforced():
    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": ["a", "b"]},
            "score": {"type": "integer", "minimum": 1, "maximum": 10},
            "name": {"type": "string", "minLength": 2, "maxLength": 4, "pattern": "^[a-z]+$"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }

    assert validate(schema, {"label": "a", "score": 5, "name": "abc", "tags": ["x"]}, "r") is None
    assert validate(schema, {"label": "c"}, "r") == 'Field label must be one of: "a", "b"'
    assert validate(schema, {"score": 0}, "r") == "Field score must be at least 1"
    assert validate(schema, {"score": 11}, "r") == "Field score must be at most 10"
    assert validate(schema, {"name": "a"}, "r") == "Field name must be at least 2 characters long"
    assert validate(schema, {"name": "abcde"}, "r") == "Field name must be at most 4 characters long"
    assert validate(schema, {"name": "AB"}, "r") == "Field name must match pattern ^[a-z]+$"
    assert validate(schema, {"tags": ["x", 2]}, "r") == "Field tags[1] must be of type string, got integer"


def test_booleans_are_not_numbers():
    assert validate({"type": "integer"}, True, "response") == (
        "Field response must be of type integer, got boolean"
    )


def test_check_output_passes_text_through_without_a_schema():
    check = check_output(None, "plain text")

    assert check.valid and check.value == "plain text"


def test_build_schema_rejects_an_uncompilable_pattern():
    try:
        build_schema({"properties": {"name": {"pattern": "["}}}, "task")
    except Exception as exc:
        assert "not a valid regular expression" in str(exc)
    else:
        raise AssertionError("an invalid pattern should be rejected")

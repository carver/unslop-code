"""Structured output: JSON parsing and draft-7 schema validation."""

from __future__ import annotations

import json

from conftest import base_task
from fake_api import FakeAPI, Reply, always, sequence
from taskrunner.schema import validate

CODE_SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}


def schema_task(api_url: str, schema: dict = None, **overrides) -> dict:
    """A task whose output must satisfy `schema`, with no evaluation by default."""
    task = base_task(api_url, output_schema=schema or CODE_SCHEMA, output_field="code")
    task.pop("evaluation")
    task.update(overrides)
    return task


def reply(payload) -> Reply:
    return Reply(content=json.dumps(payload))


# Spec: "support JSON Schema draft 7 rules for type".
# Context: Structured Output Validation / Rules.
def test_type_keyword():
    assert validate("hi", {"type": "string"}) is None
    assert validate(3, {"type": "string"}) is not None
    assert validate(3, {"type": "integer"}) is None
    assert validate(3.5, {"type": "number"}) is None
    assert validate(3.5, {"type": "integer"}) is not None
    assert validate(True, {"type": "boolean"}) is None
    assert validate(True, {"type": "integer"}) is not None
    assert validate(None, {"type": "null"}) is None
    assert validate([1], {"type": "array"}) is None
    assert validate({}, {"type": "object"}) is None


# Spec: "support JSON Schema draft 7 rules for ... required, properties".
# Context: Structured Output Validation / Rules.
def test_required_and_properties_keywords():
    assert validate({"code": "x", "explanation": "y"}, CODE_SCHEMA) is None
    assert "explanation" in validate({"code": "x"}, CODE_SCHEMA)
    assert validate({"code": 1, "explanation": "y"}, CODE_SCHEMA) is not None


# Spec: "support JSON Schema draft 7 rules for ... items".
# Context: Structured Output Validation / Rules.
def test_items_keyword():
    schema = {"type": "array", "items": {"type": "integer"}}
    assert validate([1, 2, 3], schema) is None
    assert validate([1, "two"], schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... enum".
# Context: Structured Output Validation / Rules.
def test_enum_keyword():
    schema = {"enum": ["a", "b"]}
    assert validate("a", schema) is None
    assert validate("c", schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... minimum, maximum".
# Context: Structured Output Validation / Rules.
def test_minimum_and_maximum_keywords():
    schema = {"type": "number", "minimum": 1, "maximum": 10}
    assert validate(1, schema) is None
    assert validate(10, schema) is None
    assert validate(0.5, schema) is not None
    assert validate(11, schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... minLength, maxLength".
# Context: Structured Output Validation / Rules.
def test_length_keywords():
    schema = {"type": "string", "minLength": 2, "maxLength": 4}
    assert validate("ab", schema) is None
    assert validate("abcd", schema) is None
    assert validate("a", schema) is not None
    assert validate("abcde", schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... pattern".
# Context: Structured Output Validation / Rules.
def test_pattern_keyword():
    schema = {"type": "string", "pattern": "^v[0-9]+$"}
    assert validate("v12", schema) is None
    assert validate("x12", schema) is not None


# Spec: draft 7 ignores keywords that do not apply to the instance's type.
# Context: Structured Output Validation / Rules; nested schemas still apply.
def test_nested_schemas_are_validated():
    schema = {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {"type": "array", "items": {"type": "object", "required": ["id"]}}
        },
    }
    assert validate({"items": [{"id": 1}]}, schema) is None
    assert validate({"items": [{"name": "x"}]}, schema) is not None


# Spec: "when output_schema is present, parse the model response as JSON and
# validate it before running any other evaluation" and "on schema success,
# store the parsed JSON value in the per-row output field instead of the raw
# response string".
# Context: Structured Output Validation / Rules and Examples.
def test_successful_structured_output(write_config, write_input, run_cli):
    payload = {"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}
    with FakeAPI(responder=sequence([reply(payload)])) as api:
        config = write_config(schema_task(api.url))
        data = write_input([{"question": "add", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["output"] == {"code": payload}
    assert row["result"]["passed"] is True
    assert row["result"]["schema_valid"] is True


# Spec: "on schema failure for non-rejection rows, set output to null,
# result.schema_valid to false, and result.schema_error to a human-readable
# validation message."
# Context: Structured Output Validation / Examples.
def test_schema_failure_for_a_non_rejection_row(write_config, write_input, run_cli):
    with FakeAPI(responder=sequence([reply({"code": "def add(): pass"})])) as api:
        config = write_config(schema_task(api.url))
        data = write_input([{"question": "add", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["schema_valid"] is False
    assert "explanation" in row["result"]["schema_error"]


# Spec: "invalid JSON also counts as a schema failure".
# Context: Structured Output Validation / Rules.
def test_invalid_json_is_a_schema_failure(write_config, write_input, run_cli):
    with FakeAPI(responder=always("not json at all")) as api:
        config = write_config(schema_task(api.url))
        data = write_input([{"question": "add", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert row["result"]["schema_error"]


# Spec: "for greedy and sample, schema failure sets result.passed to false".
# Context: Structured Output Validation / Rules.
def test_sample_rows_fail_on_schema_failure(write_config, write_input, run_cli):
    with FakeAPI(responder=always("{}")) as api:
        task = schema_task(api.url, generation={"scheme": "sample", "temperature": 0.7})
        config = write_config(task)
        data = write_input([{"question": "add", "answer": "5"}])
        result = run_cli(config, data)
    assert result.rows[0]["result"]["passed"] is False
    assert result.rows[0]["result"]["schema_valid"] is False
    assert result.summary["failed"] == 1


# Spec: "rejection sampling may use output_schema even when no separate
# evaluation block is configured" and "for rejection sampling, schema failure
# is a failed attempt and may trigger another try".
# Context: Structured Output Validation / Rules.
def test_rejection_retries_until_the_schema_holds(write_config, write_input, run_cli):
    good = reply({"code": "ok", "explanation": "fine"})
    replies = [Reply(content="{}"), Reply(content="{}"), good]
    with FakeAPI(responder=sequence(replies)) as api:
        task = schema_task(
            api.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 5}
        )
        config = write_config(task)
        data = write_input([{"question": "add", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 3
    row = result.rows[0]
    assert row["output"] == {"code": {"code": "ok", "explanation": "fine"}}
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 3


# Spec: "if both schema validation and evaluation are configured, run schema
# validation first and skip evaluation when schema validation fails."
# Context: Structured Output Validation / Rules; a failing script evaluation
# would exit non-zero, but it never runs.
def test_evaluation_is_skipped_when_the_schema_fails(write_config, write_input, run_cli):
    with FakeAPI(responder=always("{}")) as api:
        task = schema_task(api.url)
        task["evaluation"] = {
            "type": "script",
            "command_template": 'bash -c "exit 0"',
            "success_exit_code": 0,
        }
        config = write_config(task)
        data = write_input([{"question": "add", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["result"]["schema_valid"] is False
    assert row["result"]["passed"] is False


# Spec: "run schema validation first and skip evaluation when schema
# validation fails" — a valid document still has to pass the evaluation.
# Context: Structured Output Validation / Rules.
def test_evaluation_runs_after_a_valid_schema(write_config, write_input, run_cli):
    payload = {"code": "x", "explanation": "the answer is 7"}
    with FakeAPI(responder=sequence([reply(payload)])) as api:
        task = schema_task(api.url)
        task["evaluation"] = {"type": "contains", "answer_field": "answer"}
        config = write_config(task)
        data = write_input([{"question": "add", "answer": "7"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is True

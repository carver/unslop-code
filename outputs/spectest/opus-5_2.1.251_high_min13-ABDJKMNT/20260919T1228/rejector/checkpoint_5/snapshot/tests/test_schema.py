"""Structured output: JSON parsing and draft-7 validation before evaluation."""

from __future__ import annotations

import json

from conftest import make_config

OBJECT_SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {
        "code": {"type": "string"},
        "explanation": {"type": "string"},
    },
}
VALID = json.dumps({"code": "def add(a, b): return a + b", "explanation": "Simple"})
ROW = [{"question": "write add", "answer": "1"}]


def schema_config(server_url, schema=None, **overrides):
    """A greedy task that requires structured output and nothing else."""
    settings = {
        "output_schema": OBJECT_SCHEMA if schema is None else schema,
        "output_field": "code",
        "evaluation": None,
        **overrides,
    }
    return make_config(server_url, **settings)


def run_schema(servers, run_cli, response, schema=None, **overrides):
    server = servers(contents=[response])
    return run_cli(schema_config(server.url, schema, **overrides), ROW)


# Spec: "on schema success, store the parsed JSON value in the per-row `output`
# field instead of the raw response string", with `result.schema_valid` true.
def test_valid_structured_output_is_stored_parsed(servers, run_cli):
    result = run_schema(servers, run_cli, VALID)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["output"] == {
        "code": {
            "code": "def add(a, b): return a + b",
            "explanation": "Simple",
        }
    }
    assert result.rows[0]["result"]["schema_valid"] is True
    assert result.rows[0]["result"]["passed"] is True


# Spec: "on schema failure for non-rejection rows, set `output` to `null`,
# `result.schema_valid` to `false`, and `result.schema_error` to a
# human-readable validation message."
def test_missing_required_field_fails_the_row(servers, run_cli):
    result = run_schema(servers, run_cli, json.dumps({"code": "x"}))
    assert result.exit_code == 0, result.stderr
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert row["result"]["schema_error"] == "Missing required field: explanation"
    assert row["result"]["passed"] is False


# Spec: "invalid JSON also counts as a schema failure."
def test_invalid_json_is_a_schema_failure(servers, run_cli):
    result = run_schema(servers, run_cli, "here is some code: def add(...)")
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert row["result"]["schema_error"]


# Spec: "for `greedy` and `sample`, schema failure sets `result.passed` to
# `false`" -- for `sample` too.
def test_sample_scheme_fails_on_schema_failure(servers, run_cli):
    result = run_schema(
        servers,
        run_cli,
        json.dumps({"code": 5, "explanation": "no"}),
        generation={"scheme": "sample", "temperature": 0.7},
    )
    assert result.rows[0]["result"]["passed"] is False
    assert result.summary["failed"] == 1


# Spec: draft 7 `type` -- a member of the wrong type fails validation.
def test_type_rule(servers, run_cli):
    result = run_schema(
        servers, run_cli, json.dumps({"code": 5, "explanation": "text"})
    )
    assert result.rows[0]["result"]["schema_valid"] is False
    assert "code" in result.rows[0]["result"]["schema_error"]


# Spec: draft 7 `items` -- every element of an array is validated.
def test_items_rule(servers, run_cli):
    schema = {"type": "array", "items": {"type": "integer"}}
    passing = run_schema(servers, run_cli, "[1, 2, 3]", schema)
    assert passing.rows[0]["result"]["schema_valid"] is True
    assert passing.rows[0]["output"] == {"code": [1, 2, 3]}
    failing = run_schema(servers, run_cli, '[1, "two"]', schema)
    assert failing.rows[0]["result"]["schema_valid"] is False


# Spec: draft 7 `enum`.
def test_enum_rule(servers, run_cli):
    schema = {"type": "object", "properties": {"code": {"enum": ["a", "b"]}}}
    passing = run_schema(servers, run_cli, json.dumps({"code": "a"}), schema)
    assert passing.rows[0]["result"]["schema_valid"] is True
    failing = run_schema(servers, run_cli, json.dumps({"code": "c"}), schema)
    assert failing.rows[0]["result"]["schema_valid"] is False


# Spec: draft 7 `minimum` and `maximum`.
def test_minimum_and_maximum_rules(servers, run_cli):
    schema = {"type": "number", "minimum": 1, "maximum": 10}
    assert run_schema(servers, run_cli, "5", schema).rows[0]["result"]["schema_valid"]
    assert not run_schema(servers, run_cli, "0", schema).rows[0]["result"]["schema_valid"]
    assert not run_schema(servers, run_cli, "11", schema).rows[0]["result"]["schema_valid"]


# Spec: draft 7 `minLength` and `maxLength`.
def test_length_rules(servers, run_cli):
    schema = {"type": "string", "minLength": 2, "maxLength": 4}
    assert run_schema(servers, run_cli, '"abc"', schema).rows[0]["result"]["schema_valid"]
    assert not run_schema(servers, run_cli, '"a"', schema).rows[0]["result"]["schema_valid"]
    assert not run_schema(servers, run_cli, '"abcde"', schema).rows[0]["result"][
        "schema_valid"
    ]


# Spec: draft 7 `pattern`.
def test_pattern_rule(servers, run_cli):
    schema = {"type": "string", "pattern": "^v[0-9]+$"}
    assert run_schema(servers, run_cli, '"v12"', schema).rows[0]["result"]["schema_valid"]
    assert not run_schema(servers, run_cli, '"12"', schema).rows[0]["result"][
        "schema_valid"
    ]


# Spec: "rejection sampling may use `output_schema` even when no separate
# `evaluation` block is configured", and "for rejection sampling, schema
# failure is a failed attempt and may trigger another try".
def test_rejection_retries_after_a_schema_failure(servers, run_cli):
    server = servers(contents=["not json", "still not json", VALID])
    config = schema_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 3}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 3
    assert result.rows[0]["result"]["attempts"] == 3
    assert result.rows[0]["result"]["passed"] is True
    assert result.rows[0]["output"]["code"]["explanation"] == "Simple"


# Spec: "when `output_schema` is present, parse the model response as JSON and
# validate it before running any other evaluation" -- and "skip evaluation when
# schema validation fails", so an evaluation that would have passed is not run.
def test_schema_failure_skips_evaluation(servers, run_cli):
    server = servers(contents=["#### 1"])
    config = schema_config(
        server.url,
        evaluation={
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
    )
    result = run_cli(config, ROW)
    assert result.rows[0]["result"]["schema_valid"] is False
    assert result.rows[0]["result"]["passed"] is False
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "if both schema validation and evaluation are configured, run schema
# validation first" -- a valid document is then evaluated as usual. (T94)
def test_evaluation_runs_after_a_valid_schema(servers, run_cli):
    server = servers(contents=[json.dumps({"code": "x", "explanation": "1"})])
    config = schema_config(
        server.url,
        evaluation={
            "type": "contains",
            "answer_field": "answer",
            "extract": "full",
        },
    )
    result = run_cli(config, ROW)
    assert result.rows[0]["result"]["schema_valid"] is True
    assert result.rows[0]["result"]["passed"] is True

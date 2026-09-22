"""Spec section: Structured Output Validation (`output_schema`)."""
from __future__ import annotations

import json

import pytest

from conftest import base_config, judge_responder, rows_of
from mock_server import MockAPI, always, completion, sequence

CODE_SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {
        "code": {"type": "string"},
        "explanation": {"type": "string"},
    },
}

GOOD = json.dumps({"code": "def add(a, b): return a + b",
                   "explanation": "Simple addition function"})
MISSING = json.dumps({"code": "def add(a, b): return a + b"})


def schema_config(api_url, schema=None, **over):
    """A task whose output must satisfy `schema`; no evaluation by default."""
    over.setdefault("evaluation", None)
    over.setdefault("output_field", "code")
    return base_config(api_url, output_schema=schema or CODE_SCHEMA, **over)


# ---------------------------------------------------------------------------
# Phrase: "when `output_schema` is present, parse the model response as JSON
#          and validate it" / "on schema success, store the parsed JSON value
#          in the per-row `output` field instead of the raw response string"
# Context: Structured Output Validation - the "Successful structured output"
# example.
# ---------------------------------------------------------------------------
def test_valid_structured_output(run_tool, write_config, write_input):
    with MockAPI(always(GOOD)) as api:
        cfg = write_config(schema_config(api.url))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] == {"code": {"code": "def add(a, b): return a + b",
                                      "explanation": "Simple addition function"}}
    assert row["result"]["passed"] is True
    assert row["result"]["schema_valid"] is True


# ---------------------------------------------------------------------------
# Phrase: "on schema failure for non-rejection rows, set `output` to `null`,
#          `result.schema_valid` to `false`, and `result.schema_error` to a
#          human-readable validation message"
# Phrase: "for `greedy` and `sample`, schema failure sets `result.passed` to
#          `false`"
# Context: Structured Output Validation - the "Schema failure" example.
# ---------------------------------------------------------------------------
def test_schema_failure_row_shape(run_tool, write_config, write_input):
    with MockAPI(always(MISSING)) as api:
        cfg = write_config(schema_config(api.url))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["schema_valid"] is False
    error = row["result"]["schema_error"]
    assert isinstance(error, str) and error
    assert "explanation" in error


# Context: Structured Output Validation - `sample` behaves like `greedy`.
def test_schema_failure_for_sample_scheme(run_tool, write_config, write_input):
    with MockAPI(always(MISSING)) as api:
        cfg = write_config(schema_config(
            api.url, generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False
    assert res.rows[0]["result"]["schema_valid"] is False


# ---------------------------------------------------------------------------
# Phrase: "invalid JSON also counts as a schema failure"
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_invalid_json_is_a_schema_failure(run_tool, write_config, write_input):
    with MockAPI(always("here is your code: def add(a, b)")) as api:
        cfg = write_config(schema_config(api.url))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert isinstance(row["result"]["schema_error"], str)
    assert row["result"]["schema_error"]


# ---------------------------------------------------------------------------
# Phrase: "support JSON Schema draft 7 rules for `type`, `required`,
#          `properties`, `items`, `enum`, `minimum`, `maximum`, `minLength`,
#          `maxLength`, and `pattern`"
# Context: Structured Output Validation.  One case per keyword, valid/invalid.
# ---------------------------------------------------------------------------
KEYWORD_CASES = [
    # (schema, response text, expected schema_valid)
    ({"type": "object"}, '{"a": 1}', True),
    ({"type": "object"}, '[1, 2]', False),
    ({"type": "array"}, '[1, 2]', True),
    ({"type": "string"}, '"hello"', True),
    ({"type": "string"}, '5', False),
    ({"type": "integer"}, '5', True),
    ({"type": "integer"}, '5.5', False),
    ({"type": "number"}, '5.5', True),
    ({"type": "boolean"}, 'true', True),
    ({"type": "null"}, 'null', True),
    ({"type": "object", "required": ["a"]}, '{"a": 1}', True),
    ({"type": "object", "required": ["a", "b"]}, '{"a": 1}', False),
    ({"type": "object", "properties": {"a": {"type": "string"}}},
     '{"a": "x"}', True),
    ({"type": "object", "properties": {"a": {"type": "string"}}},
     '{"a": 3}', False),
    ({"type": "array", "items": {"type": "integer"}}, '[1, 2, 3]', True),
    ({"type": "array", "items": {"type": "integer"}}, '[1, "two"]', False),
    ({"enum": ["yes", "no"]}, '"yes"', True),
    ({"enum": ["yes", "no"]}, '"maybe"', False),
    ({"type": "number", "minimum": 10}, '10', True),
    ({"type": "number", "minimum": 10}, '9.5', False),
    ({"type": "number", "maximum": 10}, '10', True),
    ({"type": "number", "maximum": 10}, '10.5', False),
    ({"type": "string", "minLength": 3}, '"abc"', True),
    ({"type": "string", "minLength": 3}, '"ab"', False),
    ({"type": "string", "maxLength": 3}, '"abc"', True),
    ({"type": "string", "maxLength": 3}, '"abcd"', False),
    ({"type": "string", "pattern": "^[0-9]+$"}, '"1234"', True),
    ({"type": "string", "pattern": "^[0-9]+$"}, '"12a4"', False),
]


@pytest.mark.parametrize("schema,text,valid", KEYWORD_CASES)
def test_draft7_keywords(run_tool, write_config, write_input, schema, text,
                         valid):
    with MockAPI(always(text)) as api:
        cfg = write_config(schema_config(api.url, schema))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["schema_valid"] is valid, row
    if valid:
        assert row["output"] == {"code": json.loads(text)}
    else:
        assert row["output"] is None


# Context: Structured Output Validation - nested properties are validated too.
def test_nested_schema_validation(run_tool, write_config, write_input):
    schema = {
        "type": "object",
        "required": ["result"],
        "properties": {
            "result": {
                "type": "object",
                "required": ["score"],
                "properties": {"score": {"type": "integer", "minimum": 0}},
            },
        },
    }
    bad = json.dumps({"result": {"score": -1}})
    with MockAPI(always(bad)) as api:
        cfg = write_config(schema_config(api.url, schema))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["schema_valid"] is False


# ---------------------------------------------------------------------------
# Phrase: "if both schema validation and evaluation are configured, run schema
#          validation first and skip evaluation when schema validation fails"
# Context: Structured Output Validation.  The judge would be a second API call;
# it must never happen when the schema fails.
# ---------------------------------------------------------------------------
def test_evaluation_is_skipped_when_schema_fails(run_tool, write_config,
                                                 write_input):
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only a "
                      "single integer from 1 to 10.",
            "user": "Rate this response:\n{__response__}\n\nScore:",
        },
        "threshold": 7,
        "extract": "first_number",
        "answer_field": None,
    }
    with MockAPI(judge_responder(gen_text=MISSING)) as api:
        cfg = write_config(schema_config(api.url, evaluation=evaluation))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1, "the judge ran even though schema validation failed"
    assert res.rows[0]["result"]["passed"] is False
    assert res.rows[0]["result"]["schema_valid"] is False


# Context: Structured Output Validation - a schema-valid row still has to pass
# the configured evaluation.
def test_schema_valid_row_still_runs_evaluation(run_tool, write_config,
                                                write_input):
    evaluation = {"type": "contains", "answer_field": "answer",
                  "extract": "full"}
    with MockAPI(always(GOOD)) as api:
        cfg = write_config(schema_config(api.url, evaluation=evaluation))
        data = write_input([{"question": "q0", "answer": "nowhere to be found"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is False
    assert row["output"] == {"code": json.loads(GOOD)}


# ---------------------------------------------------------------------------
# Phrase: "rejection sampling may use `output_schema` even when no separate
#          `evaluation` block is configured"
# Phrase: "for rejection sampling, schema failure is a failed attempt and may
#          trigger another try"
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_rejection_retries_on_schema_failure(run_tool, write_config,
                                             write_input):
    with MockAPI(sequence([MISSING, "not json at all", GOOD])) as api:
        cfg = write_config(schema_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3, calls
    row = res.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"code": json.loads(GOOD)}


def test_rejection_config_without_evaluation_is_valid(run_tool, write_config,
                                                      write_input):
    with MockAPI(always(GOOD)) as api:
        cfg = write_config(schema_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 2}))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.stderr.strip() == "", res.stderr
    assert all(row["result"]["passed"] is True for row in res.rows)


def test_rejection_exhausts_attempts_on_schema_failure(run_tool, write_config,
                                                       write_input):
    with MockAPI(always(MISSING)) as api:
        cfg = write_config(schema_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3, calls
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False

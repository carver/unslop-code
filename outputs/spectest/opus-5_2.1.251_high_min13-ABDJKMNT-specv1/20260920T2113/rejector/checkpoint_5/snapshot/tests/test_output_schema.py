"""Structured output: `output_schema` in a task, and the rows it produces."""

from __future__ import annotations

import json

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import multi_config, numbered_rows, task_config
from tests.fake_api import ok

#: The spec's `code_gen` output schema.
SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}

GOOD = json.dumps({"code": "def add(a, b): return a + b",
                   "explanation": "Simple addition function"})
MISSING_FIELD = json.dumps({"code": "def add(a, b): return a + b"})


def schema_config(server, **overrides):
    """A greedy task requiring the spec's schema and nothing else."""
    config = task_config(api_url=server.url, rpm=600, output_schema=SCHEMA,
                         output_field="code", **overrides)
    config["task"].pop("evaluation")
    return config


# "output_schema:\n  type: \"object\"\n  required: [...]" loads as the task's schema
def test_output_schema_loads(cli):
    config = task_config(output_schema=SCHEMA)
    assert load_config(cli.write_config(config), {}).only.output_schema == SCHEMA


# "output_schema" must be a schema mapping to be usable
def test_output_schema_must_be_a_mapping(cli):
    with pytest.raises(ConfigError, match="output_schema"):
        load_config(cli.write_config(task_config(output_schema=["object"])), {})


# "on schema success, store the parsed JSON value in the per-row `output` field
#  instead of the raw response string"
# '{"output": {"code": {"code": "def add(a, b): return a + b", ...}}}'
def test_valid_output_is_stored_parsed(cli, api):
    server = api(lambda index, body: ok(GOOD))
    run = cli.run(schema_config(server), numbered_rows(2))
    assert run.returncode == 0
    assert run.rows[0]["output"]["code"] == json.loads(GOOD)


# '"result": {"passed": true, "schema_valid": true}'
def test_valid_output_reports_schema_valid(cli, api):
    server = api(lambda index, body: ok(GOOD))
    run = cli.run(schema_config(server), numbered_rows(1))
    assert run.rows[0]["result"]["schema_valid"] is True
    assert run.rows[0]["result"]["passed"] is True


# "on schema failure for non-rejection rows, set `output` to `null`,
#  `result.schema_valid` to `false`, and `result.schema_error` to a
#  human-readable validation message"
# '{"output": null, "result": {"passed": false, "schema_valid": false,
#   "schema_error": "Missing required field: explanation"}}'
def test_schema_failure_row_shape(cli, api):
    server = api(lambda index, body: ok(MISSING_FIELD))
    run = cli.run(schema_config(server), numbered_rows(1))
    assert run.returncode == 0
    result = run.rows[0]["result"]
    assert run.rows[0]["output"] is None
    assert result["schema_valid"] is False
    assert result["schema_error"] == "Missing required field: explanation"


# "for `greedy` and `sample`, schema failure sets `result.passed` to `false`"
@pytest.mark.parametrize("generation", [
    {"scheme": "greedy"}, {"scheme": "sample", "temperature": 0.7},
])
def test_schema_failure_fails_the_row(cli, api, generation):
    server = api(lambda index, body: ok(MISSING_FIELD))
    run = cli.run(schema_config(server, generation=generation), numbered_rows(1))
    assert run.rows[0]["result"]["passed"] is False
    assert run.summary["failed"] == 1


# "invalid JSON also counts as a schema failure"
def test_invalid_json_fails_the_row(cli, api):
    server = api(lambda index, body: ok("Sure! Here is the code you asked for."))
    run = cli.run(schema_config(server), numbered_rows(1))
    assert run.rows[0]["output"] is None
    assert run.rows[0]["result"]["schema_valid"] is False
    assert "JSON" in run.rows[0]["result"]["schema_error"]


# "rejection sampling may use `output_schema` even when no separate `evaluation`
#  block is configured"
def test_rejection_may_rely_on_the_schema_alone(cli, api):
    server = api(lambda index, body: ok(GOOD))
    config = schema_config(
        server, generation={"scheme": "rejection", "temperature": 0.7, "n": 3},
    )
    run = cli.run(config, numbered_rows(1))
    assert run.returncode == 0
    assert run.rows[0]["output"]["code"] == json.loads(GOOD)
    assert run.rows[0]["result"]["passed"] is True


# "rejection sampling may use `output_schema` even when no separate `evaluation`
#  block is configured" - so such a config is no longer rejected
def test_rejection_without_evaluation_or_schema_is_still_invalid(cli):
    config = task_config(generation={"scheme": "rejection", "temperature": 0.7, "n": 2})
    config["task"].pop("evaluation")
    with pytest.raises(ConfigError, match="output_schema"):
        load_config(cli.write_config(config), {})


# "for rejection sampling, schema failure is a failed attempt and may trigger
#  another try"
def test_rejection_retries_after_a_schema_failure(cli, api):
    server = api(lambda index, body: ok(MISSING_FIELD if index == 0 else GOOD))
    config = schema_config(
        server, generation={"scheme": "rejection", "temperature": 0.7, "n": 3},
    )
    run = cli.run(config, numbered_rows(1))
    assert len(server.log.calls) == 2
    assert run.rows[0]["result"]["attempts"] == 2
    assert run.rows[0]["output"]["code"] == json.loads(GOOD)


# "for rejection sampling, schema failure is a failed attempt" - every attempt
# failing the schema spends the budget and leaves no output
def test_rejection_gives_up_when_no_attempt_conforms(cli, api):
    server = api(lambda index, body: ok(MISSING_FIELD))
    config = schema_config(
        server, generation={"scheme": "rejection", "temperature": 0.7, "n": 3},
    )
    run = cli.run(config, numbered_rows(1))
    assert len(server.log.calls) == 3
    assert run.rows[0]["output"] is None
    assert run.rows[0]["result"]["passed"] is False


# "when `output_schema` is present, parse the model response as JSON and validate
#  it before running any other evaluation"
# "if both schema validation and evaluation are configured, run schema validation
#  first and skip evaluation when schema validation fails"
def test_evaluation_is_skipped_when_the_schema_fails(cli, api):
    server = api(lambda index, body: ok("plainly not json"))
    config = multi_config("review", defaults={"api_url": server.url, "rpm": 600})
    config["tasks"]["review"]["output_schema"] = SCHEMA
    run = cli.run_multi(config, {"review": [{"prompt_text": "Describe the sea.",
                                             "criteria": "vividness"}]})
    assert run.returncode == 0
    # only the generation call: the judge call an `llm_judge` task would make is
    # never sent, because schema validation comes first
    assert run.summary["total_api_calls"] == 1
    assert run.task_rows("review")[0]["result"]["schema_valid"] is False


# "if both schema validation and evaluation are configured, run schema validation
#  first" - evaluation still decides a row whose output conforms
def test_evaluation_runs_when_the_schema_passes(cli, api):
    answer = json.dumps({"code": "x", "explanation": "#### 5"})
    server = api(lambda index, body: ok(answer))
    config = task_config(api_url=server.url, rpm=600, output_schema=SCHEMA,
                         output_field="code")
    run = cli.run(config, [{"question": "2+3?", "answer": "5"},
                           {"question": "2+2?", "answer": "9"}])
    assert [row["result"]["passed"] for row in run.rows] == [True, False]
    assert [row["result"]["schema_valid"] for row in run.rows] == [True, True]
    assert run.rows[1]["output"]["code"] == json.loads(answer)


# "on schema success, store the parsed JSON value in the per-row `output` field"
# - multi-solution rows carry one parsed value per solution
def test_multi_solution_rows_store_parsed_values(cli, api):
    server = api(lambda index, body: ok(GOOD))
    config = schema_config(
        server, num_solutions=2, generation={"scheme": "sample", "temperature": 0.7},
    )
    run = cli.run(config, numbered_rows(1))
    assert [entry["code"] for entry in run.rows[0]["output"]] == [json.loads(GOOD)] * 2
    assert [entry["schema_valid"] for entry in run.rows[0]["meta"]] == [True, True]

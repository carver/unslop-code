"""`output_schema`: draft-7 validation of the model's JSON response."""

from __future__ import annotations

import json

from fake_server import FakeAPIServer, always, cycle
from conftest import base_config

from rejector_core.schema import validate_document

CODE_SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}
VALID_DOC = {"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}


def _rows(write_input, count=1):
    return write_input([{"question": f"q{i}", "answer": "5"} for i in range(count)])


def _schema_config(api_url, *, schema=None, evaluation=None, **overrides):
    """A task validating `schema`, with evaluation dropped unless asked for."""
    config = base_config(api_url, **overrides)
    config["task"]["output_schema"] = schema or CODE_SCHEMA
    if evaluation is None:
        config["task"].pop("evaluation")
    else:
        config["task"]["evaluation"] = evaluation
    return config


# Spec: "support JSON Schema draft 7 rules for `type`"
def test_type_keyword_accepts_and_rejects():
    assert validate_document("hello", {"type": "string"}) is None
    assert validate_document(5, {"type": "string"}) is not None


# Spec: draft 7 `type` - integers are numbers but booleans are not
def test_numeric_types_follow_json_schema():
    assert validate_document(5, {"type": "number"}) is None
    assert validate_document(5.5, {"type": "integer"}) is not None
    assert validate_document(True, {"type": "integer"}) is not None


# Spec: "support JSON Schema draft 7 rules for ... `required`"
def test_required_names_the_missing_field():
    error = validate_document({"code": "x"}, CODE_SCHEMA)
    assert error == "Missing required field: explanation"


# Spec: "support JSON Schema draft 7 rules for ... `properties`"
def test_properties_are_validated_recursively():
    assert validate_document({"code": 1, "explanation": "x"}, CODE_SCHEMA) is not None


# Spec: "support JSON Schema draft 7 rules for ... `items`"
def test_items_validates_every_array_element():
    schema = {"type": "array", "items": {"type": "integer"}}
    assert validate_document([1, 2, 3], schema) is None
    assert validate_document([1, "two"], schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... `enum`"
def test_enum_restricts_the_allowed_values():
    schema = {"enum": ["a", "b"]}
    assert validate_document("a", schema) is None
    assert validate_document("c", schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... `minimum`, `maximum`"
def test_minimum_and_maximum_bound_numbers():
    schema = {"type": "number", "minimum": 1, "maximum": 5}
    assert validate_document(3, schema) is None
    assert validate_document(0, schema) is not None
    assert validate_document(6, schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... `minLength`, `maxLength`"
def test_min_and_max_length_bound_strings():
    schema = {"type": "string", "minLength": 2, "maxLength": 4}
    assert validate_document("abc", schema) is None
    assert validate_document("a", schema) is not None
    assert validate_document("abcde", schema) is not None


# Spec: "support JSON Schema draft 7 rules for ... `pattern`"
def test_pattern_matches_anywhere_in_the_string():
    schema = {"type": "string", "pattern": "^ab"}
    assert validate_document("abc", schema) is None
    assert validate_document("xab", schema) is not None


# Spec: "on schema success, store the parsed JSON value in the per-row
# `output` field instead of the raw response string"
def test_valid_response_is_stored_parsed(write_config, write_input, run_cli):
    with FakeAPIServer(always(json.dumps(VALID_DOC))) as api:
        config = write_config(_schema_config(api.url))
        result = run_cli(config, _rows(write_input))

    assert result.rows[0]["output"] == {"solution": VALID_DOC}
    assert result.rows[0]["result"]["schema_valid"] is True
    assert result.rows[0]["result"]["passed"] is True


# Spec: "on schema failure for non-rejection rows, set `output` to `null`,
# `result.schema_valid` to `false`, and `result.schema_error` to a
# human-readable validation message"
def test_schema_failure_nulls_the_output(write_config, write_input, run_cli):
    with FakeAPIServer(always(json.dumps({"code": "x"}))) as api:
        config = write_config(_schema_config(api.url))
        result = run_cli(config, _rows(write_input))

    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert row["result"]["schema_error"] == "Missing required field: explanation"


# Spec: "for `greedy` and `sample`, schema failure sets `result.passed` to
# `false`"
def test_schema_failure_marks_the_row_failed(write_config, write_input, run_cli):
    with FakeAPIServer(always(json.dumps({"code": "x"}))) as api:
        config = write_config(_schema_config(api.url))
        result = run_cli(config, _rows(write_input))

    assert result.rows[0]["result"]["passed"] is False
    assert result.summary["failed"] == 1


# Spec: "invalid JSON also counts as a schema failure"
def test_non_json_response_is_a_schema_failure(write_config, write_input, run_cli):
    with FakeAPIServer(always("just prose, no JSON here")) as api:
        config = write_config(_schema_config(api.url))
        result = run_cli(config, _rows(write_input))

    assert result.rows[0]["result"]["schema_valid"] is False
    assert result.rows[0]["result"]["schema_error"]


# Spec: "if both schema validation and evaluation are configured, run schema
# validation first and skip evaluation when schema validation fails"
def test_evaluation_is_skipped_when_the_schema_fails(write_config, write_input, run_cli):
    evaluation = {"type": "llm_judge", "threshold": 4,
                  "judge_prompt": {"system": "Score", "user": "{question}"}}
    with FakeAPIServer(always("not json")) as api:
        config = write_config(_schema_config(api.url, evaluation=evaluation))
        result = run_cli(config, _rows(write_input))
        calls = len(api.requests)

    assert calls == 1
    assert result.rows[0]["result"]["passed"] is False


# Spec: "run schema validation first" - a document that validates still has
# to satisfy the configured evaluation
def test_evaluation_still_decides_passed_for_valid_documents(write_config, write_input, run_cli):
    evaluation = {"type": "contains", "answer_field": "answer"}
    with FakeAPIServer(always(json.dumps(VALID_DOC))) as api:
        config = write_config(_schema_config(api.url, evaluation=evaluation))
        result = run_cli(config, _rows(write_input))

    assert result.rows[0]["result"]["schema_valid"] is True
    assert result.rows[0]["result"]["passed"] is False


# Spec: "for rejection sampling, schema failure is a failed attempt and may
# trigger another try"
def test_rejection_retries_after_a_schema_failure(write_config, write_input, run_cli):
    replies = ["not json", json.dumps(VALID_DOC)]
    with FakeAPIServer(cycle(replies)) as api:
        config = _schema_config(api.url)
        config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3}
        result = run_cli(write_config(config), _rows(write_input))
        calls = len(api.requests)

    assert calls == 2
    assert result.rows[0]["output"] == {"solution": VALID_DOC}
    assert result.rows[0]["result"]["passed"] is True


# Spec: "rejection sampling may use `output_schema` even when no separate
# `evaluation` block is configured"
def test_rejection_without_evaluation_is_accepted(write_config, write_input, run_cli):
    with FakeAPIServer(always(json.dumps(VALID_DOC))) as api:
        config = _schema_config(api.url)
        config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 2}
        result = run_cli(write_config(config), _rows(write_input))

    assert result.returncode == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: "rejection ... may trigger another try" - a row that never validates
# ends with a null output after its budget is spent
def test_rejection_that_never_validates_writes_null(write_config, write_input, run_cli):
    with FakeAPIServer(always("not json")) as api:
        config = _schema_config(api.url)
        config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 2}
        result = run_cli(write_config(config), _rows(write_input))
        calls = len(api.requests)

    assert calls == 2
    assert result.rows[0]["output"] is None
    assert result.rows[0]["result"]["passed"] is False


# Spec: "when `output_schema` is present, parse the model response as JSON"
# - a task without the block keeps the raw string output
def test_without_the_block_output_stays_a_string(write_config, write_input, run_cli):
    with FakeAPIServer(always(json.dumps(VALID_DOC))) as api:
        config = base_config(api.url)
        config["task"].pop("evaluation")
        result = run_cli(write_config(config), _rows(write_input))

    assert result.rows[0]["output"] == {"solution": json.dumps(VALID_DOC)}
    assert "schema_valid" not in result.rows[0]["result"]


# Spec: "when `output_schema` is present, parse the model response ... and
# validate it" - the block is merged from `defaults` like other sections
def test_output_schema_merges_from_defaults(write_config, write_input, run_argv):
    from conftest import GSM8K_TASK, multi_config

    with FakeAPIServer(always(json.dumps(VALID_DOC))) as api:
        config_map = multi_config(api.url, {"gsm8k": dict(GSM8K_TASK)})
        config_map["defaults"]["output_schema"] = CODE_SCHEMA
        config_map["tasks"]["gsm8k"].pop("evaluation")
        config = write_config(config_map)
        rows = write_input([{"question": "q", "answer": "5"}], name="gsm8k.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={rows}")

    assert result.task_rows("gsm8k")[0]["result"]["schema_valid"] is True

"""Structured Output Validation section."""

import json

import pytest

import fake_api

SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {
        "code": {"type": "string"},
        "explanation": {"type": "string"},
    },
}

GOOD = {"code": "def add(a, b): return a + b",
        "explanation": "Simple addition function"}


def schema_task(**over):
    task = {"output_schema": json.loads(json.dumps(SCHEMA)),
            "output_field": "code",
            "evaluation": None}
    task.update(over)
    return task


# ---------------------------------------------------------------------------
# Spec: "on schema success, store the parsed JSON value in the per-row `output`
#        field instead of the raw response string"
# Spec example: {"output": {"code": {"code": ..., "explanation": ...}},
#                "result": {"passed": true, "schema_valid": true}}
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_successful_structured_output(run_task):
    with fake_api.FakeAPI(fake_api.always(json.dumps(GOOD))) as api:
        res = run_task(api, task=schema_task(), check=0)
    row = res.rows[0]
    assert row["output"] == {"code": GOOD}
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "on schema failure for non-rejection rows, set `output` to `null`,
#        `result.schema_valid` to `false`, and `result.schema_error` to a
#        human-readable validation message"
# Spec example: "schema_error": "Missing required field: explanation"
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_schema_failure_for_a_non_rejection_row(run_task):
    body = json.dumps({"code": "def add(a, b): return a + b"})
    with fake_api.FakeAPI(fake_api.always(body)) as api:
        res = run_task(api, task=schema_task(), check=0)
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert row["result"]["schema_error"] == "Missing required field: explanation"


# ---------------------------------------------------------------------------
# Spec: "for `greedy` and `sample`, schema failure sets `result.passed` to
#        `false`"
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scheme,temperature", [("greedy", 0.0),
                                                ("sample", 0.7)])
def test_schema_failure_sets_passed_false(run_task, scheme, temperature):
    with fake_api.FakeAPI(fake_api.always("nonsense")) as api:
        res = run_task(api,
                       task=schema_task(generation={"scheme": scheme,
                                                    "temperature": temperature}),
                       check=0)
    row = res.rows[0]
    assert row["result"]["passed"] is False
    assert row["result"]["schema_valid"] is False
    assert res.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Spec: "invalid JSON also counts as a schema failure"
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_invalid_json_is_a_schema_failure(run_task):
    with fake_api.FakeAPI(fake_api.always("here you go: {code: 1")) as api:
        res = run_task(api, task=schema_task(), check=0)
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["schema_valid"] is False
    assert isinstance(row["result"]["schema_error"], str)
    assert row["result"]["schema_error"]


# ---------------------------------------------------------------------------
# Spec: "rejection sampling may use `output_schema` even when no separate
#        `evaluation` block is configured"
# Spec: "for rejection sampling, schema failure is a failed attempt and may
#        trigger another try"
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_rejection_retries_after_a_schema_failure(run_task):
    responses = ["not json at all", json.dumps(GOOD)]
    with fake_api.FakeAPI(fake_api.sequence(responses)) as api:
        res = run_task(api,
                       task=schema_task(generation={"scheme": "rejection",
                                                    "temperature": 0.8,
                                                    "n": 3}),
                       check=0)
    assert api.call_count == 2
    row = res.rows[0]
    assert row["output"] == {"code": GOOD}
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Spec: "rejection sampling may use `output_schema` even when no separate
#        `evaluation` block is configured"
# Context: Structured Output Validation.  Exhausting the attempts leaves the
# row failed, not a configuration error.
# ---------------------------------------------------------------------------
def test_rejection_with_schema_only_and_no_success(run_task):
    with fake_api.FakeAPI(fake_api.always("nope")) as api:
        res = run_task(api,
                       task=schema_task(generation={"scheme": "rejection",
                                                    "temperature": 0.8,
                                                    "n": 2}),
                       check=0)
    assert api.call_count == 2
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "if both schema validation and evaluation are configured, run schema
#        validation first and skip evaluation when schema validation fails"
# Context: Structured Output Validation.  The judge call never happens.
# ---------------------------------------------------------------------------
def test_evaluation_is_skipped_when_the_schema_fails(run_task):
    judge = fake_api.dispatch(
        lambda rec: "Rate" in (rec.system_content or ""),
        fake_api.always("1.0"), fake_api.always("not json"))
    with fake_api.FakeAPI(judge) as api:
        res = run_task(api,
                       task=schema_task(evaluation={
                           "type": "llm_judge",
                           "judge_prompt": {"system": "Rate the answer 0..1.",
                                            "user": "{__response__}"},
                           "threshold": 0.5}),
                       check=0)
    assert api.call_count == 1, "evaluation ran despite the schema failure"
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "when `output_schema` is present, parse the model response as JSON and
#        validate it before running any other evaluation"
# Context: Structured Output Validation.  A valid document still has to pass
# the evaluation (AMBIGUITIES T97: evaluation reads the raw response text).
# ---------------------------------------------------------------------------
def test_evaluation_runs_after_a_valid_schema(run_task):
    body = json.dumps({"code": "x = 5", "explanation": "the answer is 5"})
    with fake_api.FakeAPI(fake_api.always(body)) as api:
        res = run_task(api,
                       task=schema_task(evaluation={
                           "type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"}),
                       rows=[{"question": "q", "answer": "5"}], check=0)
    row = res.rows[0]
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is True
    assert row["output"]["code"] == json.loads(body)


def test_valid_schema_but_failing_evaluation(run_task):
    body = json.dumps({"code": "x = 9", "explanation": "nine"})
    with fake_api.FakeAPI(fake_api.always(body)) as api:
        res = run_task(api,
                       task=schema_task(evaluation={
                           "type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"}),
                       rows=[{"question": "q", "answer": "5"}], check=0)
    row = res.rows[0]
    assert row["result"]["schema_valid"] is True
    assert row["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "when `output_schema` is present" -- rows of a task without one keep
# the earlier shape.
# Context: Structured Output Validation.
# ---------------------------------------------------------------------------
def test_no_schema_keeps_the_earlier_row_shape(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    row = res.rows[0]
    assert row["output"] == {"solution": "#### 5"}
    assert "schema_valid" not in row["result"]
    assert "schema_error" not in row["result"]


# ---------------------------------------------------------------------------
# Spec: "schema_error" is only about failures.
# Context: Structured Output Validation.  A passing row carries no error text.
# ---------------------------------------------------------------------------
def test_no_schema_error_on_success(run_task):
    with fake_api.FakeAPI(fake_api.always(json.dumps(GOOD))) as api:
        res = run_task(api, task=schema_task(), check=0)
    assert "schema_error" not in res.rows[0]["result"]


# ---------------------------------------------------------------------------
# Spec: "support JSON Schema draft 7 rules for `type`, `required`,
#        `properties`, `items`, `enum`, `minimum`, `maximum`, `minLength`,
#        `maxLength`, and `pattern`"
# Context: Structured Output Validation.  Keyword-level unit tests.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("schema,value", [
    ({"type": "object"}, {}),
    ({"type": "array"}, []),
    ({"type": "string"}, "x"),
    ({"type": "number"}, 1.5),
    ({"type": "number"}, 2),
    ({"type": "integer"}, 7),
    ({"type": "boolean"}, True),
    ({"type": "null"}, None),
    ({"type": ["string", "null"]}, None),
    ({"required": ["a"]}, {"a": 1}),
    ({"properties": {"a": {"type": "string"}}}, {"a": "s"}),
    ({"properties": {"a": {"type": "string"}}}, {}),
    ({"type": "array", "items": {"type": "integer"}}, [1, 2, 3]),
    ({"enum": ["a", "b"]}, "b"),
    ({"minimum": 3}, 3),
    ({"maximum": 3}, 3),
    ({"minLength": 2}, "ab"),
    ({"maxLength": 2}, "ab"),
    ({"pattern": "^a.c$"}, "abc"),
    ({"type": "object", "properties": {
        "inner": {"type": "object", "required": ["x"]}}},
     {"inner": {"x": 1}}),
])
def test_schema_keyword_accepts(rejector, schema, value):
    assert rejector.schema_error(value, schema) is None


@pytest.mark.parametrize("schema,value", [
    ({"type": "object"}, []),
    ({"type": "array"}, {}),
    ({"type": "string"}, 5),
    ({"type": "number"}, "5"),
    ({"type": "integer"}, 1.5),
    ({"type": "integer"}, True),
    ({"type": "number"}, True),
    ({"type": "boolean"}, "true"),
    ({"type": "null"}, 0),
    ({"type": ["string", "null"]}, 3),
    ({"required": ["a", "b"]}, {"a": 1}),
    ({"properties": {"a": {"type": "string"}}}, {"a": 5}),
    ({"type": "array", "items": {"type": "integer"}}, [1, "x"]),
    ({"enum": ["a", "b"]}, "c"),
    ({"minimum": 3}, 2.5),
    ({"maximum": 3}, 4),
    ({"minLength": 2}, "a"),
    ({"maxLength": 2}, "abc"),
    ({"pattern": "^a.c$"}, "abd"),
    ({"type": "object", "properties": {
        "inner": {"type": "object", "required": ["x"]}}},
     {"inner": {}}),
])
def test_schema_keyword_rejects(rejector, schema, value):
    error = rejector.schema_error(value, schema)
    assert isinstance(error, str) and error


# ---------------------------------------------------------------------------
# Spec: "schema_error": "Missing required field: explanation"
# Context: Structured Output Validation.  The quoted message, verbatim.
# ---------------------------------------------------------------------------
def test_missing_required_message(rejector):
    error = rejector.schema_error({"code": "x"}, SCHEMA)
    assert error == "Missing required field: explanation"


# ---------------------------------------------------------------------------
# Spec: "output_schema" on a task in a multi-task config, merged from defaults.
# Context: Structured Output Validation (AMBIGUITIES T110).
# ---------------------------------------------------------------------------
def test_output_schema_per_task_in_multi_config(run_multi):
    with fake_api.FakeAPI(fake_api.always(json.dumps(GOOD))) as api:
        res = run_multi(api,
                        tasks={"gsm8k": {"output_schema": SCHEMA,
                                         "evaluation": None,
                                         "output_field": "code"}},
                        check=0)
    row = res.task_rows("gsm8k")[0]
    assert row["output"] == {"code": GOOD}
    assert row["result"]["schema_valid"] is True


# ---------------------------------------------------------------------------
# Spec: "output_schema: type: object ..."
# Context: Structured Output Validation.  A malformed schema is a config error.
# ---------------------------------------------------------------------------
def test_invalid_output_schema_is_a_configuration_error(run_task):
    res = run_task(task={"output_schema": "object"}, check=1)
    assert "error" in res.stderr.lower()

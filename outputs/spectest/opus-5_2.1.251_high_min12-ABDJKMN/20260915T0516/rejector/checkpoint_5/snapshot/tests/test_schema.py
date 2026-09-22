"""Part 5: structured output validation against `output_schema`."""
import json

import pytest

import rejector
from conftest import OBJECT_SCHEMA, make_config
from mock_api import MockAPI, always, sequence


GOOD = json.dumps({"code": "def add(a, b): return a + b",
                   "explanation": "Simple addition function"})
MISSING = json.dumps({"code": "def add(a, b): return a + b"})


def schema_config(api_url, schema=None, **kw):
    kw.setdefault("evaluation", None)
    kw.setdefault("output_field", "code")
    return make_config(api_url=api_url,
                       output_schema=OBJECT_SCHEMA if schema is None else schema,
                       **kw)


# ------------------------------------------------------- the validator ---

# Spec: "support JSON Schema draft 7 rules for `type` ..."
# Context: Structured Output Validation / Rules.
@pytest.mark.parametrize("value,type_name,ok", [
    ("x", "string", True),
    (1, "string", False),
    (1, "integer", True),
    (1.5, "integer", False),
    (True, "integer", False),
    (1.5, "number", True),
    (1, "number", True),
    (True, "boolean", True),
    (1, "boolean", False),
    ({}, "object", True),
    ([], "object", False),
    ([], "array", True),
    (None, "null", True),
    ("x", "null", False),
])
def test_type_keyword(value, type_name, ok):
    error = rejector.validate_schema(value, {"type": type_name})
    assert (error is None) is ok


# Spec: "... `required` ..."
def test_required_keyword_names_the_missing_field():
    error = rejector.validate_schema({"code": "x"}, OBJECT_SCHEMA)
    assert error is not None
    assert "explanation" in error


def test_required_keyword_passes_when_present():
    assert rejector.validate_schema({"code": "a", "explanation": "b"},
                                    OBJECT_SCHEMA) is None


# Spec: "... `properties` ..."
def test_properties_are_validated():
    error = rejector.validate_schema({"code": 7, "explanation": "b"},
                                     OBJECT_SCHEMA)
    assert error is not None
    assert "code" in error


def test_properties_not_listed_are_allowed():
    assert rejector.validate_schema({"code": "a", "explanation": "b",
                                     "extra": 1}, OBJECT_SCHEMA) is None


# Spec: "... `items` ..."
def test_items_validates_every_element():
    schema = {"type": "array", "items": {"type": "string"}}
    assert rejector.validate_schema(["a", "b"], schema) is None
    assert rejector.validate_schema(["a", 2], schema) is not None


# Spec: "... `enum` ..."
def test_enum_keyword():
    schema = {"enum": ["yes", "no"]}
    assert rejector.validate_schema("yes", schema) is None
    assert rejector.validate_schema("maybe", schema) is not None


# Spec: "... `minimum`, `maximum` ..."
def test_minimum_and_maximum_are_inclusive():
    schema = {"type": "number", "minimum": 1, "maximum": 10}
    assert rejector.validate_schema(1, schema) is None
    assert rejector.validate_schema(10, schema) is None
    assert rejector.validate_schema(0.9, schema) is not None
    assert rejector.validate_schema(10.1, schema) is not None


# Spec: "... `minLength`, `maxLength` ..."
def test_min_and_max_length():
    schema = {"type": "string", "minLength": 2, "maxLength": 4}
    assert rejector.validate_schema("ab", schema) is None
    assert rejector.validate_schema("abcd", schema) is None
    assert rejector.validate_schema("a", schema) is not None
    assert rejector.validate_schema("abcde", schema) is not None


# Spec: "... and `pattern`"
def test_pattern_keyword():
    schema = {"type": "string", "pattern": "^ab"}
    assert rejector.validate_schema("abc", schema) is None
    assert rejector.validate_schema("xabc", schema) is not None


# Spec: nested objects validate through `properties`.
def test_nested_object_errors_name_the_path():
    schema = {"type": "object",
              "properties": {"inner": {"type": "object",
                                       "required": ["k"],
                                       "properties": {"k": {"type": "integer"}}}}}
    assert rejector.validate_schema({"inner": {"k": 1}}, schema) is None
    error = rejector.validate_schema({"inner": {"k": "x"}}, schema)
    assert error is not None and "k" in error


# Spec: "invalid JSON also counts as a schema failure"
# Context: Structured Output Validation / Rules.
def test_invalid_json_is_a_schema_failure():
    ok, value, error = rejector.check_output_schema("not json at all",
                                                    OBJECT_SCHEMA)
    assert ok is False
    assert value is None
    assert error


def test_valid_json_parses_to_its_value():
    ok, value, error = rejector.check_output_schema(GOOD, OBJECT_SCHEMA)
    assert ok is True
    assert error is None
    assert value == json.loads(GOOD)


# ------------------------------------------------------------ end to end ---

# Spec: the successful structured-output example:
#   {"output": {"code": {...}}, "result": {"passed": true,
#    "schema_valid": true}}
# Context: Structured Output Validation / Examples.
def test_valid_structured_output_is_stored_parsed(run_tool):
    with MockAPI(always(GOOD)) as api:
        run = run_tool(schema_config(api.url), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    record = run.rows[0]
    assert record["output"] == {"code": {
        "code": "def add(a, b): return a + b",
        "explanation": "Simple addition function"}}
    assert record["result"]["schema_valid"] is True
    assert record["result"]["passed"] is True


# Spec: the schema-failure example:
#   {"output": null, "result": {"passed": false, "schema_valid": false,
#    "schema_error": "Missing required field: explanation"}}
# Context: Structured Output Validation / Examples.
def test_schema_failure_row_shape(run_tool):
    with MockAPI(always(MISSING)) as api:
        run = run_tool(schema_config(api.url), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    record = run.rows[0]
    assert record["output"] is None
    assert record["result"]["passed"] is False
    assert record["result"]["schema_valid"] is False
    assert "explanation" in record["result"]["schema_error"]


# Spec: "invalid JSON also counts as a schema failure"
def test_unparsable_response_fails_the_row(run_tool):
    with MockAPI(always("here you go: def add(a, b)...")) as api:
        run = run_tool(schema_config(api.url), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    record = run.rows[0]
    assert record["output"] is None
    assert record["result"]["schema_valid"] is False
    assert isinstance(record["result"]["schema_error"], str)
    assert record["result"]["schema_error"]


# Spec: "for `greedy` and `sample`, schema failure sets `result.passed` to
#        `false`"
# Context: Structured Output Validation / Rules.
def test_sample_scheme_schema_failure_sets_passed_false(run_tool):
    with MockAPI(always(MISSING)) as api:
        run = run_tool(schema_config(api.url, scheme="sample",
                                     temperature=0.7), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


# Spec: "run schema validation first and skip evaluation when schema
#        validation fails"
# Context: Structured Output Validation / Rules. The evaluation here would
# have passed on the raw text, so a passing row proves it was skipped.
def test_evaluation_is_skipped_when_the_schema_fails(run_tool):
    evaluation = {"type": "contains", "answer_field": "answer"}
    rows = [{"question": "q", "answer": "def add"}]
    with MockAPI(always(MISSING)) as api:
        run = run_tool(schema_config(api.url, evaluation=evaluation), rows)
    assert run.returncode == 0, run.stderr
    record = run.rows[0]
    assert record["result"]["passed"] is False
    assert record["result"]["schema_valid"] is False


# Spec: "when `output_schema` is present, parse the model response as JSON and
#        validate it before running any other evaluation"
# Context: a valid document still has to satisfy the evaluation.
def test_evaluation_still_runs_when_the_schema_passes(run_tool):
    evaluation = {"type": "contains", "answer_field": "answer"}
    with MockAPI(always(GOOD)) as api:
        run = run_tool(schema_config(api.url, evaluation=evaluation),
                       [{"question": "q", "answer": "nowhere in the response"}])
    assert run.returncode == 0, run.stderr
    record = run.rows[0]
    assert record["result"]["schema_valid"] is True
    assert record["result"]["passed"] is False


def test_evaluation_and_schema_can_both_pass(run_tool):
    evaluation = {"type": "contains", "answer_field": "answer"}
    with MockAPI(always(GOOD)) as api:
        run = run_tool(schema_config(api.url, evaluation=evaluation),
                       [{"question": "q", "answer": "Simple addition"}])
    assert run.returncode == 0, run.stderr
    record = run.rows[0]
    assert record["result"]["schema_valid"] is True
    assert record["result"]["passed"] is True


# Spec: "rejection sampling may use `output_schema` even when no separate
#        `evaluation` block is configured"
# Context: Structured Output Validation / Rules. Without a schema this config
# would be rejected for missing `evaluation`.
def test_rejection_without_evaluation_is_valid_with_a_schema(run_tool):
    with MockAPI(always(GOOD)) as api:
        run = run_tool(schema_config(api.url, scheme="rejection",
                                     temperature=0.7, n=3), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 1
    assert run.rows[0]["result"]["passed"] is True


# Spec: "for rejection sampling, schema failure is a failed attempt and may
#        trigger another try"
# Context: Structured Output Validation / Rules.
def test_rejection_retries_after_a_schema_failure(run_tool):
    with MockAPI(sequence([MISSING, "nonsense", GOOD])) as api:
        run = run_tool(schema_config(api.url, scheme="rejection",
                                     temperature=0.7, n=3), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    record = run.rows[0]
    assert record["result"]["attempts"] == 3
    assert record["result"]["passed"] is True
    assert record["output"]["code"] == json.loads(GOOD)


# Spec: rejection exhausts its attempts when every response fails the schema.
def test_rejection_exhausts_attempts_on_repeated_schema_failure(run_tool):
    with MockAPI(always(MISSING)) as api:
        run = run_tool(schema_config(api.url, scheme="rejection",
                                     temperature=0.7, n=2), [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    record = run.rows[0]
    assert record["result"]["attempts"] == 2
    assert record["result"]["passed"] is False
    assert record["output"] is None


# Spec: "on schema success, store the parsed JSON value in the per-row
#        `output` field instead of the raw response string"
# Context: a non-object schema still stores the parsed value.
def test_scalar_schema_stores_the_parsed_value(run_tool):
    schema = {"type": "array", "items": {"type": "integer"}}
    with MockAPI(always("[1, 2, 3]")) as api:
        run = run_tool(schema_config(api.url, schema=schema),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"]["code"] == [1, 2, 3]


# Spec: rows without a schema keep the Part 1 shape (no schema keys).
def test_no_schema_keys_when_no_schema_is_configured(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    result = run.rows[0]["result"]
    assert "schema_valid" not in result
    assert "schema_error" not in result

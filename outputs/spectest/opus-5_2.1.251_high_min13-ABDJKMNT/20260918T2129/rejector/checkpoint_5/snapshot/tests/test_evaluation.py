"""Evaluation types and extract methods."""

from __future__ import annotations

import pytest
from fake_server import FakeAPIServer, always
from conftest import base_config


def _run(write_config, write_input, run_cli, evaluation, content, row):
    config_map = base_config("")
    config_map["task"]["evaluation"] = evaluation
    with FakeAPIServer(always(content)) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        return run_cli(config, write_input([row]))


# Spec: "exact_match: extract an answer from the response and compare it to
# the configured answer_field from the input row"
def test_exact_match_passes_when_extracted_equals_answer(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "Let me solve this step by step.\n5 + 3 = 8\n#### 8",
        {"question": "q", "answer": "8"},
    )
    assert result.rows[0]["result"]["passed"] is True
    assert result.rows[0]["result"]["extracted_answer"] == "8"


# Spec: "exact_match: ... compare it to the configured answer_field"
def test_exact_match_fails_when_extracted_differs(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "#### 7",
        {"question": "q", "answer": "8"},
    )
    assert result.rows[0]["result"]["passed"] is False
    assert result.rows[0]["result"]["extracted_answer"] == "7"


# Spec: "contains: response text must contain the answer_field value as a
# substring"
def test_contains_passes_on_substring(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "contains", "answer_field": "answer"},
        "The capital is Paris, France.",
        {"question": "q", "answer": "Paris"},
    )
    assert result.rows[0]["result"]["passed"] is True


# Spec: "contains: response text must contain the answer_field value"
def test_contains_fails_when_absent(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "contains", "answer_field": "answer"},
        "The capital is Berlin.",
        {"question": "q", "answer": "Paris"},
    )
    assert result.rows[0]["result"]["passed"] is False


# Spec: "contains: ... the answer_field value" - non-string row values compare
# by their textual form
def test_contains_handles_numeric_answer_values(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "contains", "answer_field": "answer"},
        "the total is 42 items",
        {"question": "q", "answer": 42},
    )
    assert result.rows[0]["result"]["passed"] is True


# Spec: "regex: response text must match the configured pattern"
def test_regex_passes_when_pattern_matches(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "regex", "pattern": r"####\s*\d+"},
        "reasoning\n#### 42",
        {"question": "q"},
    )
    assert result.rows[0]["result"]["passed"] is True


# Spec: "regex: response text must match the configured pattern"
def test_regex_fails_when_pattern_does_not_match(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "regex", "pattern": r"####\s*\d+"},
        "no final answer here",
        {"question": "q"},
    )
    assert result.rows[0]["result"]["passed"] is False


# Spec: "last_number: use the last integer or decimal in the response"
@pytest.mark.parametrize(
    "content,expected",
    [
        ("2 + 3 = 5\n#### 5", "5"),
        ("first 12 then 7 then 99", "99"),
        ("the answer is 3.75", "3.75"),
        ("temperature fell to -8", "-8"),
        ("#### 8\ntrailing words", "8"),
    ],
)
def test_last_number_extraction(content, expected, write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        content,
        {"question": "q", "answer": expected},
    )
    assert result.rows[0]["result"]["extracted_answer"] == expected
    assert result.rows[0]["result"]["passed"] is True


# Spec: "last_number" - a response with no number has nothing to extract
def test_last_number_with_no_number_fails(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "no digits at all",
        {"question": "q", "answer": "8"},
    )
    assert result.rows[0]["result"]["passed"] is False
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "last_line: use the last non-empty line"
def test_last_line_extraction_skips_trailing_blank_lines(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "exact_match", "answer_field": "answer", "extract": "last_line"},
        "step one\nstep two\nParis\n\n   \n",
        {"question": "q", "answer": "Paris"},
    )
    assert result.rows[0]["result"]["extracted_answer"] == "Paris"
    assert result.rows[0]["result"]["passed"] is True


# Spec: "full: use the entire response text"
def test_full_extraction_uses_whole_response(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli,
        {"type": "exact_match", "answer_field": "answer", "extract": "full"},
        "Paris",
        {"question": "q", "answer": "Paris"},
    )
    assert result.rows[0]["result"]["extracted_answer"] == "Paris"
    assert result.rows[0]["result"]["passed"] is True


# Spec: "if evaluation is omitted for greedy or sample, result.passed must be
# null"
@pytest.mark.parametrize("generation", [
    {"scheme": "greedy", "max_tokens": 64},
    {"scheme": "sample", "temperature": 0.6, "max_tokens": 64},
])
def test_passed_is_null_without_evaluation(generation, write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = generation
    del config_map["task"]["evaluation"]
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q"}]))
    assert result.rows[0]["result"]["passed"] is None


# Spec: "result.extracted_answer is ... null when there is no evaluation"
def test_extracted_answer_is_null_without_evaluation(write_config, write_input, run_cli):
    config_map = base_config("")
    del config_map["task"]["evaluation"]
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q"}]))
    assert result.rows[0]["result"]["extracted_answer"] is None

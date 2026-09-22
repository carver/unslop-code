"""Evaluation types, extract methods, and the resulting result block."""
import pytest

from conftest import make_config
from mock_api import MockAPI, always, per_question

import rejector


# ---------------------------------------------------------------- extract ---
# Spec: "last_number: use the last integer or decimal in the response"
# Context: Extract methods.
@pytest.mark.parametrize("text,expected", [
    ("2 + 3 = 5\n#### 5", "5"),
    ("first 1 then 2 then 3", "3"),
    ("the result is 3.14", "3.14"),
    ("step 1: 10 apples\n#### 42", "42"),
    ("#### 007", "007"),
])
def test_last_number_extracts_final_number(text, expected):
    assert rejector.extract_answer(text, "last_number") == expected


def test_last_number_handles_decimal_before_trailing_text():
    assert rejector.extract_answer("total was 12.50 dollars", "last_number") == "12.50"


# T10: a leading minus is part of the number.
def test_last_number_includes_negative_sign():
    assert rejector.extract_answer("#### -4", "last_number") == "-4"


def test_last_number_with_no_number_returns_none():
    assert rejector.extract_answer("no digits here", "last_number") is None


# Spec: "last_line: use the last non-empty line"
def test_last_line_skips_trailing_blank_lines():
    assert rejector.extract_answer("a\nb\nfinal answer\n\n  \n", "last_line") == \
        "final answer"


def test_last_line_of_single_line_text():
    assert rejector.extract_answer("only line", "last_line") == "only line"


# Spec: "full: use the entire response text"
def test_full_returns_whole_text():
    text = "line one\nline two\n"
    assert rejector.extract_answer(text, "full") == text


# ------------------------------------------------------------- exact_match ---
# Spec: "exact_match: extract an answer from the response and compare it to
#        the configured answer_field from the input row"
# Context: Evaluation types.
def test_exact_match_passes_when_extracted_equals_answer_field(run_tool):
    with MockAPI(always("2 + 3 = 5\n#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "What is 2 + 3?", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    result = run.rows[0]["result"]
    assert result["passed"] is True
    assert result["extracted_answer"] == "5"


def test_exact_match_fails_when_extracted_differs(run_tool):
    with MockAPI(always("I think it is 9\n#### 9")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "What is 2 + 3?", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    result = run.rows[0]["result"]
    assert result["passed"] is False
    assert result["extracted_answer"] == "9"


def test_exact_match_with_numeric_answer_field(run_tool):
    # The row's answer is a JSON number, not a string.
    with MockAPI(always("#### 8")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": 8}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


def test_exact_match_with_full_extract(run_tool):
    with MockAPI(always("Paris")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "exact_match",
                                               "answer_field": "answer",
                                               "extract": "full"}),
                       [{"question": "capital?", "answer": "Paris"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


def test_exact_match_with_last_line_extract(run_tool):
    with MockAPI(always("reasoning here\nThe answer is:\n42\n")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "exact_match",
                                               "answer_field": "answer",
                                               "extract": "last_line"}),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True
    assert run.rows[0]["result"]["extracted_answer"] == "42"


# T9: exact string comparison, whitespace stripped.
def test_exact_match_is_not_substring_matching(run_tool):
    with MockAPI(always("42000")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "exact_match",
                                               "answer_field": "answer",
                                               "extract": "full"}),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------- contains ---
# Spec: "contains: response text must contain the answer_field value as a
#        substring"
def test_contains_passes_when_substring_present(run_tool):
    with MockAPI(always("The capital of France is Paris, obviously.")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "contains",
                                               "answer_field": "answer"}),
                       [{"question": "capital?", "answer": "Paris"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


def test_contains_fails_when_substring_absent(run_tool):
    with MockAPI(always("The capital of France is Lyon.")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "contains",
                                               "answer_field": "answer"}),
                       [{"question": "capital?", "answer": "Paris"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


# T11: extracted_answer is the configured extraction (default `full`) even for
# contains/regex evaluations.
def test_contains_reports_extracted_answer(run_tool):
    with MockAPI(always("it is Paris")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "contains",
                                               "answer_field": "answer"}),
                       [{"question": "capital?", "answer": "Paris"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["extracted_answer"] == "it is Paris"


# ------------------------------------------------------------------- regex ---
# Spec: "regex: response text must match the configured pattern"
def test_regex_passes_on_match(run_tool):
    with MockAPI(always("blah blah\n#### 17")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "regex",
                                               "pattern": r"####\s*\d+"}),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


def test_regex_fails_on_no_match(run_tool):
    with MockAPI(always("no marker at all")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "regex",
                                               "pattern": r"####\s*\d+"}),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


def test_invalid_regex_pattern_exits_1(run_tool):
    run = run_tool(make_config(evaluation={"type": "regex", "pattern": "([a-z"}),
                   [{"question": "q"}])
    assert run.returncode == 1
    assert run.stderr.strip()


# ------------------------------------------------------------ no evaluation --
# Spec: "if evaluation is omitted for greedy or sample, result.passed must be
#        null"
# Context: Validation rules.
def test_passed_is_null_without_evaluation(run_tool):
    with MockAPI(always("some text")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is None


# Spec: "result.extracted_answer is ... null when there is no evaluation"
def test_extracted_answer_is_null_without_evaluation(run_tool):
    with MockAPI(always("some text")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["extracted_answer"] is None


# T8: extract defaults to `full` when omitted.
def test_extract_defaults_to_full(run_tool):
    with MockAPI(always("Paris")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   evaluation={"type": "exact_match",
                                               "answer_field": "answer"}),
                       [{"question": "q", "answer": "Paris"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True

"""Extraction methods and evaluation types."""

from __future__ import annotations

import asyncio

import pytest

from conftest import base_task

from taskrunner.config import build_run_config
from taskrunner.evaluation import evaluate as evaluate_async, extract_answer


def evaluation_for(**fields):
    task = base_task("http://localhost:8000")
    task["evaluation"] = fields
    config = next(iter(build_run_config({"task": task}, {}).tasks.values()))
    return config.evaluation


def evaluate(text: str, row: dict, config):
    """`(passed, extracted)` for the evaluation types that need no API call."""
    outcome = asyncio.run(evaluate_async(text, row, config, None))
    return outcome.passed, outcome.extracted


# Spec: "last_number: use the last integer or decimal in the response"
# Context: Extract methods.
def test_last_number_picks_the_final_integer():
    assert extract_answer("2 + 3 = 5\n#### 5", "last_number") == "5"


def test_last_number_picks_the_final_number_among_many():
    assert extract_answer("first 1 then 22 then 333", "last_number") == "333"


def test_last_number_handles_decimals():
    assert extract_answer("the speed is 30.5 mph", "last_number") == "30.5"


def test_last_number_handles_negatives():
    assert extract_answer("the balance is -42", "last_number") == "-42"


def test_last_number_ignores_a_trailing_sentence_period():
    assert extract_answer("The answer is 8.", "last_number") == "8"


# Spec: "last_number: use the last integer or decimal in the response"
# Context: Extract methods; nothing to extract when the text has no number.
def test_last_number_without_any_number_is_none():
    assert extract_answer("no digits here", "last_number") is None


# Spec: "last_line: use the last non-empty line"
# Context: Extract methods.
def test_last_line_uses_the_last_non_empty_line():
    assert extract_answer("alpha\nbeta\n\n  \n", "last_line") == "beta"


def test_last_line_strips_surrounding_whitespace():
    assert extract_answer("alpha\n   beta   ", "last_line") == "beta"


def test_last_line_of_blank_text_is_none():
    assert extract_answer("   \n\n", "last_line") is None


# Spec: "full: use the entire response text"
# Context: Extract methods.
def test_full_returns_entire_text():
    assert extract_answer("line one\nline two", "full") == "line one\nline two"


# Spec: "exact_match: extract an answer from the response and compare it to the
# configured answer_field from the input row"
# Context: Evaluation types.
def test_exact_match_passes_when_extracted_equals_answer():
    cfg = evaluation_for(type="exact_match", answer_field="answer", extract="last_number")
    passed, extracted = evaluate("2 + 3 = 5\n#### 5", {"answer": "5"}, cfg)
    assert (passed, extracted) == (True, "5")


def test_exact_match_fails_on_different_value():
    cfg = evaluation_for(type="exact_match", answer_field="answer", extract="last_number")
    passed, extracted = evaluate("#### 7", {"answer": "5"}, cfg)
    assert (passed, extracted) == (False, "7")


def test_exact_match_compares_against_stringified_row_value():
    cfg = evaluation_for(type="exact_match", answer_field="answer", extract="last_number")
    assert evaluate("#### 8", {"answer": 8}, cfg)[0] is True


def test_exact_match_fails_when_nothing_extracted():
    cfg = evaluation_for(type="exact_match", answer_field="answer", extract="last_number")
    passed, extracted = evaluate("no number", {"answer": "5"}, cfg)
    assert (passed, extracted) == (False, None)


# Spec: "contains: response text must contain the answer_field value as a
# substring"
# Context: Evaluation types; the check runs against the whole response.
def test_contains_matches_substring_anywhere_in_response():
    cfg = evaluation_for(type="contains", answer_field="answer")
    assert evaluate("the answer is Paris, France", {"answer": "Paris"}, cfg)[0] is True


def test_contains_fails_when_absent():
    cfg = evaluation_for(type="contains", answer_field="answer")
    assert evaluate("the answer is Lyon", {"answer": "Paris"}, cfg)[0] is False


# Spec: "result.extracted_answer is the extracted comparison value"
# Context: Output; extraction applies whatever the evaluation type
# (see AMBIGUITIES T4).
def test_contains_reports_configured_extraction():
    cfg = evaluation_for(type="contains", answer_field="answer", extract="last_line")
    passed, extracted = evaluate("thinking\nParis", {"answer": "Paris"}, cfg)
    assert (passed, extracted) == (True, "Paris")


# Spec: "regex: response text must match the configured pattern"
# Context: Evaluation types (see AMBIGUITIES T12 for search semantics).
def test_regex_passes_when_pattern_found():
    cfg = evaluation_for(type="regex", pattern=r"####\s*\d+")
    assert evaluate("work\n#### 42", {}, cfg)[0] is True


def test_regex_fails_when_pattern_absent():
    cfg = evaluation_for(type="regex", pattern=r"####\s*\d+")
    assert evaluate("no marker", {}, cfg)[0] is False


def test_regex_matches_anywhere_in_the_response():
    cfg = evaluation_for(type="regex", pattern=r"answer")
    assert evaluate("the answer is here", {}, cfg)[0] is True


# Spec: "result.passed is ... null when no evaluation is configured"
# Context: Output.
def test_no_evaluation_yields_null_verdict_and_extraction():
    assert evaluate("anything", {"answer": "5"}, None) == (None, None)


# Spec: "extract" interacts with every evaluation type.
# Context: Extract methods.
@pytest.mark.parametrize(
    "extract,expected",
    [("last_number", "5"), ("last_line", "#### 5"), ("full", "2 + 3 = 5\n#### 5")],
)
def test_extraction_method_selects_the_reported_value(extract, expected):
    cfg = evaluation_for(type="exact_match", answer_field="answer", extract=extract)
    assert evaluate("2 + 3 = 5\n#### 5", {"answer": "5"}, cfg)[1] == expected

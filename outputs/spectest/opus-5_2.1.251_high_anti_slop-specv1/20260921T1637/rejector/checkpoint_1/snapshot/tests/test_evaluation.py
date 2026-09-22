"""Unit tests for answer extraction and the evaluation checks."""

import pytest

from config import EvaluationConfig
from evaluation import evaluate, extract_answer


@pytest.mark.parametrize(
    ("method", "text", "expected"),
    [
        ("last_number", "5 + 3 = 8\n#### 8", "8"),
        ("last_number", "the total is 1,234 dollars", "1234"),
        ("last_number", "result: -2.5", "-2.5"),
        ("last_number", "no digits here", None),
        ("last_line", "first\n\n  final answer  \n\n", "final answer"),
        ("last_line", "   \n", None),
        ("full", "whole text", "whole text"),
    ],
)
def test_extract_answer(method, text, expected):
    assert extract_answer(method, text) == expected


def test_exact_match_compares_numeric_values():
    config = EvaluationConfig(type="exact_match", extract="last_number", answer_field="answer")

    assert evaluate(config, "#### 8.00", {"answer": "8"}) == (True, "8.00")
    assert evaluate(config, "#### 7", {"answer": "8"}) == (False, "7")


def test_contains_checks_the_whole_response():
    config = EvaluationConfig(type="contains", extract="full", answer_field="answer")

    assert evaluate(config, "the capital is Paris", {"answer": "Paris"})[0] is True
    assert evaluate(config, "the capital is Paris", {"answer": "Lyon"})[0] is False


def test_regex_matches_the_response_text():
    config = EvaluationConfig(type="regex", extract="last_line", pattern=r"####\s*\d+")

    assert evaluate(config, "steps\n#### 42", {}) == (True, "#### 42")
    assert evaluate(config, "steps\nno answer", {})[0] is False


def test_no_evaluation_yields_no_verdict():
    assert evaluate(None, "anything", {}) == (None, None)

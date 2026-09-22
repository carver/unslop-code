"""Unit tests for answer extraction and the evaluation checks."""

import asyncio

import pytest

import script_eval
from config import EvaluationConfig
from evaluation import evaluate
from extraction import extract_answer


def check(config, text, row=None):
    """Run one evaluation to completion and return ``(passed, extracted_answer)``."""
    result = asyncio.run(evaluate(config, text, row or {}, None))
    return result.passed, result.extracted_answer


@pytest.mark.parametrize(
    ("method", "text", "expected"),
    [
        ("last_number", "5 + 3 = 8\n#### 8", "8"),
        ("last_number", "the total is 1,234 dollars", "1234"),
        ("last_number", "result: -2.5", "-2.5"),
        ("last_number", "no digits here", None),
        ("first_number", "score: 8 out of 10", "8"),
        ("first_number", "7.5 is my rating", "7.5"),
        ("first_number", "unscored", None),
        ("last_line", "first\n\n  final answer  \n\n", "final answer"),
        ("last_line", "   \n", None),
        ("letter", "The answer is B) Paris", "B"),
        ("letter", "(C)", "C"),
        ("letter", "Answer: A", "A"),
        ("letter", "D. Madrid", "D"),
        ("letter", "no choice given", None),
        ("full", "whole text", "whole text"),
    ],
)
def test_extract_answer(method, text, expected):
    assert extract_answer(method, text) == expected


def test_exact_match_compares_numeric_values():
    config = EvaluationConfig(type="exact_match", extract="last_number", answer_field="answer")

    assert check(config, "#### 8.00", {"answer": "8"}) == (True, "8.00")
    assert check(config, "#### 7", {"answer": "8"}) == (False, "7")


def test_exact_match_on_a_multiple_choice_letter():
    config = EvaluationConfig(type="exact_match", extract="letter", answer_field="answer")

    assert check(config, "The answer is B) Paris", {"answer": "B"}) == (True, "B")
    assert check(config, "The answer is B) Paris", {"answer": "C"}) == (False, "B")


def test_contains_checks_the_whole_response():
    config = EvaluationConfig(type="contains", extract="full", answer_field="answer")

    assert check(config, "the capital is Paris", {"answer": "Paris"})[0] is True
    assert check(config, "the capital is Paris", {"answer": "Lyon"})[0] is False


def test_regex_matches_the_response_text():
    config = EvaluationConfig(type="regex", extract="last_line", pattern=r"####\s*\d+")

    assert check(config, "steps\n#### 42") == (True, "#### 42")
    assert check(config, "steps\nno answer")[0] is False


def test_no_evaluation_yields_no_verdict():
    assert check(None, "anything") == (None, None)


def test_script_substitutes_the_response_inside_a_row_field():
    config = EvaluationConfig(
        type="script",
        extract="full",
        command_template="{test_code}",
        success_exit_code=0,
    )
    row = {"test_code": "echo '{__response__}' | grep -q 'good code'"}

    assert check(config, "this is good code", row)[0] is True
    assert check(config, "this is poor code", row)[0] is False


def test_script_runs_the_generated_code_inside_the_command_template():
    config = EvaluationConfig(
        type="script", extract="full", command_template='python3 -c "{test_code}"'
    )
    row = {"test_code": "{__response__}\nassert add(2, 3) == 5"}

    assert check(config, "def add(a, b): return a + b", row)[0] is True
    assert check(config, "def add(a, b): return a * b", row)[0] is False


def test_script_honours_a_non_zero_success_exit_code():
    config = EvaluationConfig(
        type="script", extract="full", command_template="exit 3", success_exit_code=3
    )

    assert check(config, "ignored")[0] is True


def test_script_timeout_fails_the_row(monkeypatch):
    monkeypatch.setattr(script_eval, "COMMAND_TIMEOUT_SECONDS", 0.2)
    config = EvaluationConfig(type="script", extract="full", command_template="sleep 5")

    assert check(config, "ignored")[0] is False

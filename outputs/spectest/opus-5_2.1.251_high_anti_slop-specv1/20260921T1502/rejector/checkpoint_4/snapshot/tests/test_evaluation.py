"""Answer extraction and the evaluation types that need no API call."""

import asyncio
import re

import pytest

from config import Evaluation, Prompt
from errors import UsageError
from evaluation import Verdict, evaluate, extract, require_row_fields
from shell import run_command


def evaluation(**overrides):
    defaults = {
        "type": "exact_match",
        "answer_field": "answer",
        "extract": "full",
        "pattern": None,
        "judge_prompt": None,
        "threshold": None,
        "model": "gpt-4",
        "command_template": None,
        "success_exit_code": 0,
    }
    return Evaluation(**{**defaults, **overrides})


def verdict(config, text, row):
    """Evaluate a response without an API client, which these types never need."""
    return asyncio.run(evaluate(config, text, row, 0, client=None))


@pytest.mark.parametrize(
    "method, text, expected",
    [
        ("last_number", "2 + 3 = 5\n#### 8", "8"),
        ("last_number", "the price is -12.5 dollars", "-12.5"),
        ("last_number", "no digits here", None),
        ("first_number", "score: 8 out of 10", "8"),
        ("first_number", "rated 7.5 overall", "7.5"),
        ("first_number", "no digits here", None),
        ("letter", "The answer is B) Paris", "B"),
        ("letter", "(C)", "C"),
        ("letter", "Answer: A", "A"),
        ("letter", "D", "D"),
        ("letter", "none of these EFG", None),
        ("last_line", "first\n#### 8\n\n", "#### 8"),
        ("last_line", "   \n", None),
        ("full", "  answer  ", "answer"),
    ],
)
def test_extract(method, text, expected):
    assert extract(text, method) == expected


def test_exact_match_compares_the_extracted_value():
    config = evaluation(extract="last_number")
    assert verdict(config, "so the answer is 8", {"answer": "8"}) == Verdict(True, "8")
    assert verdict(config, "so the answer is 7", {"answer": "8"}) == Verdict(False, "7")


def test_exact_match_on_a_multiple_choice_letter():
    config = evaluation(extract="letter")
    row = {"question": "capital of France?", "answer": "B"}
    assert verdict(config, "The answer is B) Paris", row) == Verdict(True, "B")


def test_contains_looks_for_the_answer_as_a_substring():
    config = evaluation(type="contains")
    assert verdict(config, "the total is 42 apples", {"answer": 42}) == Verdict(True, "42")
    assert verdict(config, "the total is unknown", {"answer": 42}) == Verdict(False, None)


def test_regex_returns_the_capturing_group_when_present():
    config = evaluation(type="regex", answer_field=None, pattern=re.compile(r"####\s*(\d+)"))
    assert verdict(config, "work\n#### 12", {}) == Verdict(True, "12")
    assert verdict(config, "no marker", {}) == Verdict(False, None)


def test_no_evaluation_yields_a_null_verdict():
    assert verdict(None, "anything", {}) == Verdict(None, None)


def test_script_passes_on_the_configured_exit_code():
    config = evaluation(type="script", answer_field=None, command_template='python3 -c "{test_code}"')
    row = {"test_code": "assert 'good code' in '''{__response__}'''"}
    assert verdict(config, "this is good code", row).passed
    assert not verdict(config, "this is bad", row).passed


def test_script_substitutes_the_response_inside_a_row_field():
    config = evaluation(type="script", answer_field=None, command_template="{test_code}")
    row = {"test_code": "echo '{__response__}' | grep -q 'good code'"}
    assert verdict(config, "writing good code today", row) == Verdict(True, None)


def test_script_failure_exit_code_is_reported_as_a_failure():
    config = evaluation(type="script", answer_field=None, command_template="exit 3")
    assert verdict(config, "anything", {}) == Verdict(False, None)


def test_a_command_that_hangs_times_out():
    assert asyncio.run(run_command("sleep 5", timeout=0.2)) is None


def test_rows_must_carry_the_answer_field():
    with pytest.raises(UsageError, match="row 1: missing evaluation field 'answer'"):
        require_row_fields(evaluation(), [{"answer": "1"}, {"question": "?"}])


def test_rows_must_carry_the_judge_prompt_fields():
    config = evaluation(
        type="llm_judge",
        answer_field=None,
        judge_prompt=Prompt(system=None, user="Rate {__response__} against {criteria}"),
        threshold=7,
    )
    with pytest.raises(UsageError, match="row 0: evaluation.judge_prompt.user"):
        require_row_fields(config, [{"prompt_text": "hi"}])

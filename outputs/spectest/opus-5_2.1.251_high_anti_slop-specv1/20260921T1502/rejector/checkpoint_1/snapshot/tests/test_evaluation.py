"""Answer extraction and the three evaluation types."""

import re

import pytest

from config import Evaluation
from errors import UsageError
from evaluation import extract, judge, require_answer_fields


def evaluation(**overrides):
    defaults = {"type": "exact_match", "answer_field": "answer", "extract": "full", "pattern": None}
    return Evaluation(**{**defaults, **overrides})


@pytest.mark.parametrize(
    "method, text, expected",
    [
        ("last_number", "2 + 3 = 5\n#### 8", "8"),
        ("last_number", "the price is -12.5 dollars", "-12.5"),
        ("last_number", "no digits here", None),
        ("last_line", "first\n#### 8\n\n", "#### 8"),
        ("last_line", "   \n", None),
        ("full", "  answer  ", "answer"),
    ],
)
def test_extract(method, text, expected):
    assert extract(text, method) == expected


def test_exact_match_compares_the_extracted_value():
    config = evaluation(extract="last_number")
    assert judge(config, "so the answer is 8", {"answer": "8"}) == (True, "8")
    assert judge(config, "so the answer is 7", {"answer": "8"}) == (False, "7")


def test_contains_looks_for_the_answer_as_a_substring():
    config = evaluation(type="contains")
    assert judge(config, "the total is 42 apples", {"answer": 42}) == (True, "42")
    assert judge(config, "the total is unknown", {"answer": 42}) == (False, None)


def test_regex_returns_the_capturing_group_when_present():
    config = evaluation(type="regex", answer_field=None, pattern=re.compile(r"####\s*(\d+)"))
    assert judge(config, "work\n#### 12", {}) == (True, "12")
    assert judge(config, "no marker", {}) == (False, None)


def test_no_evaluation_yields_a_null_verdict():
    assert judge(None, "anything", {}) == (None, None)


def test_rows_must_carry_the_answer_field():
    with pytest.raises(UsageError, match="row 1: missing evaluation field 'answer'"):
        require_answer_fields(evaluation(), [{"answer": "1"}, {"question": "?"}])

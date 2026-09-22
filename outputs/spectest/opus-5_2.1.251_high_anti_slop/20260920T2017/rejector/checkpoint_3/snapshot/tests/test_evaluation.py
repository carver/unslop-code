"""Answer extraction and the three evaluation types."""

import pytest

from config import EvaluationConfig
from evaluation import evaluate, extract_answer


@pytest.mark.parametrize(
    "method, text, expected",
    [
        ("last_number", "5 + 3 = 8\n#### 8", "8"),
        ("last_number", "the total is 1,250 dollars", "1250"),
        ("last_number", "a temperature of -2.5 degrees", "-2.5"),
        ("last_number", "no digits here", None),
        ("last_line", "first\n#### 42\n\n", "#### 42"),
        ("last_line", "   \n", None),
        ("full", "  keep it all  ", "  keep it all  "),
    ],
)
def test_extract_answer(method, text, expected):
    assert extract_answer(method, text) == expected


def test_exact_match_compares_extracted_value():
    config = EvaluationConfig("exact_match", "last_number", "answer", None)
    assert evaluate(config, "so the answer is 8", {"answer": "8"}) == (True, "8")
    assert evaluate(config, "so the answer is 9", {"answer": "8"}) == (False, "9")


def test_exact_match_accepts_equivalent_numbers():
    config = EvaluationConfig("exact_match", "last_number", "answer", None)
    assert evaluate(config, "#### 8.0", {"answer": 8})[0] is True


def test_exact_match_fails_without_an_extractable_answer():
    config = EvaluationConfig("exact_match", "last_number", "answer", None)
    assert evaluate(config, "I cannot tell", {"answer": "8"}) == (False, None)


def test_contains_searches_the_whole_response():
    config = EvaluationConfig("contains", "full", "answer", None)
    assert evaluate(config, "the capital is Paris, France", {"answer": "Paris"})[0] is True
    assert evaluate(config, "the capital is Lyon", {"answer": "Paris"})[0] is False


def test_regex_matches_the_pattern():
    config = EvaluationConfig("regex", "last_line", None, r"####\s+\d+")
    assert evaluate(config, "working\n#### 12", {})[0] is True
    assert evaluate(config, "working\nno answer", {})[0] is False


def test_no_evaluation_yields_nulls():
    assert evaluate(None, "anything", {}) == (None, None)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("B", "B"),
        ("(C)", "C"),
        ("A) Paris", "A"),
        ("Answer: D", "D"),
        ("The answer is B) Paris", "B"),
        ("A train is the answer: C.", "C"),
        ("none of these", None),
    ],
)
def test_letter_extracts_the_answer_choice(text, expected):
    assert extract_answer("letter", text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Score: 8", "8"),
        ("8 out of 10", "8"),
        ("I rate it 7.5 overall", "7.5"),
        ("a loss of -3", "-3"),
        ("no digits here", None),
    ],
)
def test_first_number_extracts_the_leading_value(text, expected):
    assert extract_answer("first_number", text) == expected

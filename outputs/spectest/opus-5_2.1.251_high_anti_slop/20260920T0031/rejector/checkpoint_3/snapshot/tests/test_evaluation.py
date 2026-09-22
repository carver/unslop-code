"""Answer extraction and the three evaluation types."""

import re

import pytest

from evaluation import EXTRACTORS, EvaluationConfig, evaluate

RESPONSE = "Step one: 12 sheep.\nStep two: 3 pens.\n#### 4"


@pytest.mark.parametrize(
    "method, expected",
    [("last_number", "4"), ("first_number", "12"), ("last_line", "#### 4"), ("full", RESPONSE)],
)
def test_extractors(method, expected):
    assert EXTRACTORS[method](RESPONSE) == expected


@pytest.mark.parametrize("text, expected", [("no digits here", None), ("balance -12.5 usd", "-12.5")])
def test_last_number_edge_cases(text, expected):
    assert EXTRACTORS["last_number"](text) == expected


def exact_match(extract="last_number"):
    return EvaluationConfig(type="exact_match", extract=extract, answer_field="answer")


def test_exact_match_passes_on_equal_values():
    outcome = evaluate(RESPONSE, {"answer": "4"}, exact_match())
    assert (outcome.passed, outcome.extracted) == (True, "4")


@pytest.mark.parametrize("answer", ["1200", "1,200", 1200, 1200.0])
def test_exact_match_compares_numbers_by_value(answer):
    assert evaluate("total: 1200.00", {"answer": answer}, exact_match()).passed is True


def test_exact_match_compares_text_case_insensitively():
    config = EvaluationConfig(type="exact_match", extract="last_line", answer_field="answer")
    assert evaluate("Final: Paris", {"answer": "final: paris"}, config).passed is True


def test_exact_match_fails_on_different_value():
    outcome = evaluate(RESPONSE, {"answer": "5"}, exact_match())
    assert (outcome.passed, outcome.extracted) == (False, "4")


def test_exact_match_fails_when_nothing_extracted():
    assert evaluate("no number at all", {"answer": "4"}, exact_match()).passed is False


def test_contains_checks_the_whole_response():
    config = EvaluationConfig(type="contains", extract="last_line", answer_field="answer")
    assert evaluate(RESPONSE, {"answer": "12 sheep"}, config).passed is True
    assert evaluate(RESPONSE, {"answer": "12 goats"}, config).passed is False


def test_regex_matches_response_text():
    config = EvaluationConfig(type="regex", extract="full", pattern=re.compile(r"####\s+\d+"))
    assert evaluate(RESPONSE, {}, config).passed is True
    assert evaluate("no marker", {}, config).passed is False


@pytest.mark.parametrize(
    "text, expected",
    [("B", "B"), ("(C)", "C"), ("D) Madrid", "D"), ("The answer is B) Paris", "B"), ("Answer: A", "A")],
)
def test_letter_extracts_a_standalone_choice(text, expected):
    assert EXTRACTORS["letter"](text) == expected


@pytest.mark.parametrize("text", ["Berlin is the answer", "no choice here", "E"])
def test_letter_ignores_letters_inside_words_and_out_of_range(text):
    assert EXTRACTORS["letter"](text) is None


def test_letter_answers_pass_exact_match():
    config = EvaluationConfig(type="exact_match", extract="letter", answer_field="answer")
    assert evaluate("The answer is B) Paris", {"answer": "B"}, config).passed is True


@pytest.mark.parametrize("text, expected", [("Score: 8 of 10", "8"), ("7.5/10", "7.5"), ("none", None)])
def test_first_number_takes_the_leading_value(text, expected):
    assert EXTRACTORS["first_number"](text) == expected

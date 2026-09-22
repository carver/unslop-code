"""Extract methods and evaluation types."""

from __future__ import annotations

import pytest

from rejlib.config import Evaluation
from rejlib.evaluation import evaluate, extract_answer


# "last_number: use the last integer or decimal in the response"
@pytest.mark.parametrize("text,expected", [
    ("2 + 3 = 5\n#### 5", "5"),
    ("Let me solve this step by step.\n5 + 3 = 8\n#### 8", "8"),
    ("cost is 12.50 dollars", "12.50"),
    ("a=1 b=2 c=3", "3"),
    ("temperature dropped to -7", "-7"),
    ("no digits here", None),
])
def test_last_number(text, expected):
    assert extract_answer(text, "last_number") == expected


# "last_number: use the last integer or decimal in the response"
# (T5: comma groups are one number; a sentence period is not a decimal point)
@pytest.mark.parametrize("text,expected", [
    ("the total is 1,234", "1234"),
    ("The answer is 8.", "8"),
])
def test_last_number_boundaries(text, expected):
    assert extract_answer(text, "last_number") == expected


# "last_line: use the last non-empty line"
@pytest.mark.parametrize("text,expected", [
    ("first\nsecond\n", "second"),
    ("only line", "only line"),
    ("answer\n\n   \n", "answer"),
    ("   \n  \n", None),
])
def test_last_line(text, expected):
    assert extract_answer(text, "last_line") == expected


# "full: use the entire response text"
def test_full_extract_returns_whole_response():
    assert extract_answer("line one\nline two\n", "full") == "line one\nline two\n"


# "exact_match: extract an answer from the response and compare it to the
#  configured answer_field from the input row"
def test_exact_match_uses_extract_and_answer_field():
    evaluation = Evaluation(type="exact_match", answer_field="answer", extract="last_number")
    passed, extracted = evaluate(evaluation, "2 + 3 = 5\n#### 5", {"answer": "5"})
    assert (passed, extracted) == (True, "5")

    passed, extracted = evaluate(evaluation, "2 + 3 = 6\n#### 6", {"answer": "5"})
    assert (passed, extracted) == (False, "6")


# "exact_match" (T6: numerically equal values match; unrelated text does not)
def test_exact_match_compares_numbers_numerically():
    evaluation = Evaluation(type="exact_match", answer_field="answer", extract="last_number")
    assert evaluate(evaluation, "#### 8.0", {"answer": "8"})[0] is True
    assert evaluate(evaluation, "#### 08", {"answer": "8"})[0] is True
    assert evaluate(evaluation, "#### 9", {"answer": "8"})[0] is False


# "exact_match" with a non-numeric answer compares text
def test_exact_match_compares_text_when_not_numeric():
    evaluation = Evaluation(type="exact_match", answer_field="answer", extract="last_line")
    assert evaluate(evaluation, "reasoning\nParis", {"answer": "Paris"})[0] is True
    assert evaluate(evaluation, "reasoning\nLyon", {"answer": "Paris"})[0] is False


# "exact_match" with nothing to extract cannot pass
def test_exact_match_without_extractable_number_fails():
    evaluation = Evaluation(type="exact_match", answer_field="answer", extract="last_number")
    assert evaluate(evaluation, "I cannot tell", {"answer": "8"}) == (False, None)


# "contains: response text must contain the answer_field value as a substring"
def test_contains_checks_substring_of_response():
    evaluation = Evaluation(type="contains", answer_field="answer", extract="full")
    assert evaluate(evaluation, "the answer is 42 exactly", {"answer": "42"})[0] is True
    assert evaluate(evaluation, "the answer is 41", {"answer": "42"})[0] is False


# "contains" compares against the whole response, not only the extracted value
def test_contains_scans_entire_response():
    evaluation = Evaluation(type="contains", answer_field="answer", extract="last_line")
    assert evaluate(evaluation, "42 is the value\nthinking done", {"answer": "42"})[0] is True


# "regex: response text must match the configured pattern"
def test_regex_matches_response_text():
    evaluation = Evaluation(type="regex", pattern=r"####\s*\d+", extract="full")
    assert evaluate(evaluation, "work\n#### 17", {})[0] is True
    assert evaluate(evaluation, "work\nno marker", {})[0] is False


# "result.extracted_answer is the extracted comparison value"
# (T4: contains/regex report the configured extraction of the response)
def test_extracted_answer_for_contains_and_regex():
    contains = Evaluation(type="contains", answer_field="answer", extract="last_line")
    assert evaluate(contains, "work\n42", {"answer": "42"})[1] == "42"

    regex = Evaluation(type="regex", pattern=r"\d+", extract="last_number")
    assert evaluate(regex, "value 17", {})[1] == "17"


# "compare it to the configured answer_field from the input row"
# (non-string row values are compared by value)
def test_answer_field_may_be_numeric_in_the_row():
    evaluation = Evaluation(type="exact_match", answer_field="answer", extract="last_number")
    assert evaluate(evaluation, "#### 8", {"answer": 8})[0] is True


# "letter: extract the first uppercase answer choice `A` through `D`; accept
#  forms such as `A`, `(A)`, `A)`, or `Answer: A`"
@pytest.mark.parametrize("text,expected", [
    ("A", "A"),
    ("(A)", "A"),
    ("A)", "A"),
    ("Answer: A", "A"),
    ("The answer is B) Paris", "B"),
    ("C.", "C"),
    ("  D  ", "D"),
])
def test_letter_accepted_forms(text, expected):
    assert extract_answer(text, "letter") == expected


# "letter: extract the first uppercase answer choice `A` through `D`"
# (first choice wins; letters inside words and out-of-range letters are not choices)
@pytest.mark.parametrize("text,expected", [
    ("B) Paris, not A) London", "B"),
    ("Certainly, the Best Answer is C", "C"),
    ("E", None),
    ("a", None),
    ("no letter here", None),
])
def test_letter_boundaries(text, expected):
    assert extract_answer(text, "letter") == expected


# "first_number: extract the first integer or decimal in the response"
@pytest.mark.parametrize("text,expected", [
    ("8", "8"),
    ("Score: 9 out of 10", "9"),
    ("7.5 is my rating", "7.5"),
    ("a=1 b=2 c=3", "1"),
    ("the total is 1,234 and 5", "1234"),
    ("no digits here", None),
])
def test_first_number(text, expected):
    assert extract_answer(text, "first_number") == expected

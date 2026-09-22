"""Extract methods, exercised directly against the evaluation module."""

from __future__ import annotations

import pytest

from rejector_lib.evaluation import extract_answer


# Spec: "last_number: use the last integer or decimal in the response".
def test_last_number_picks_the_final_integer():
    assert extract_answer("2 + 3 = 5\n#### 8", "last_number") == "8"


# Spec: "last_number: ... integer or decimal".
def test_last_number_picks_a_decimal():
    assert extract_answer("the rate is 3 per hour, total 12.5", "last_number") == "12.5"


# Spec: "last_number: use the last ... number in the response" -- a signed
# value keeps its sign. (T4)
def test_last_number_keeps_a_negative_sign():
    assert extract_answer("balance: -42", "last_number") == "-42"


# Checkpoint 4 shows `"$2,730,000."` extracting as `"2730000"`, so grouped
# digits are one number and the separators are dropped. (T4)
def test_last_number_reads_a_grouped_number():
    assert extract_answer("total is $2,730,000.", "last_number") == "2730000"


# Spec: "last_number" with no number present -- nothing to extract.
def test_last_number_without_any_number_is_none():
    assert extract_answer("no digits here", "last_number") is None


# Spec: "last_line: use the last non-empty line".
def test_last_line_skips_trailing_blank_lines():
    assert extract_answer("first\nanswer: yes\n\n  \n", "last_line") == "answer: yes"


# Spec: "last_line: use the last non-empty line" -- of a single-line response.
def test_last_line_of_single_line_response():
    assert extract_answer("just this", "last_line") == "just this"


# Spec: "last_line" of an empty response -- nothing to extract.
def test_last_line_of_blank_response_is_none():
    assert extract_answer("   \n\n", "last_line") is None


# Spec: "full: use the entire response text".
def test_full_returns_the_whole_response():
    text = "line one\nline two\n#### 9"
    assert extract_answer(text, "full") == text


@pytest.mark.parametrize("method", ["last_number", "last_line", "full"])
def test_all_documented_methods_are_supported(method):
    # Spec: "Extract methods: last_number, last_line, full".
    assert extract_answer("value 7", method) is not None

"""The extract methods added in Part 2: `letter` and `first_number`."""

from __future__ import annotations

import pytest

from conftest import make_config
from rejector_lib.evaluation import extract_answer


# Spec: "letter: extract the first uppercase answer choice A through D; accept
# forms such as A, (A), A), or Answer: A".
@pytest.mark.parametrize(
    "text, expected",
    [
        ("A", "A"),
        ("(A)", "A"),
        ("A)", "A"),
        ("Answer: A", "A"),
        ("B", "B"),
        ("D.", "D"),
    ],
)
def test_letter_accepts_the_documented_forms(text, expected):
    assert extract_answer(text, "letter") == expected


# Spec: the MMLU example -- the model returns "The answer is B) Paris" and
# `letter` extracts "B".
def test_letter_extracts_from_the_mmlu_example():
    assert extract_answer("The answer is B) Paris", "letter") == "B"


# Spec: "letter: extract the *first* ... answer choice".
def test_letter_takes_the_first_choice():
    assert extract_answer("Between C and A, I pick C", "letter") == "C"


# Spec: "letter: extract the first *uppercase* answer choice A through D" --
# a lowercase letter is not a choice. (T31)
def test_letter_ignores_lowercase():
    assert extract_answer("the answer is b", "letter") is None


# Spec: "letter: ... answer choice A through D" -- E is out of range. (T31)
def test_letter_ignores_letters_past_d():
    assert extract_answer("Answer: E", "letter") is None


# Spec: "letter" against a response with no choice in it.
def test_letter_without_a_choice_is_none():
    assert extract_answer("Paris is the capital", "letter") is None


# Spec: "first_number: extract the first integer or decimal in the response".
def test_first_number_takes_the_first_integer():
    assert extract_answer("12 apples, then 7 pears", "first_number") == "12"


# Spec: "first_number: ... integer or decimal".
def test_first_number_takes_a_decimal():
    assert extract_answer("about 3.5 on average, 9 at peak", "first_number") == "3.5"


# Spec: "first_number" of a judge reply that is just a score.
def test_first_number_of_a_bare_score():
    assert extract_answer("8", "first_number") == "8"


# Spec: "first_number" keeps the sign, as `last_number` does. (T32)
def test_first_number_keeps_a_negative_sign():
    assert extract_answer("delta -4 then 9", "first_number") == "-4"


# Spec: "first_number" with no number present.
def test_first_number_without_any_number_is_none():
    assert extract_answer("no digits here", "first_number") is None


# Spec: the MMLU example end to end -- the config's user template renders the
# choices, the model answers "The answer is B) Paris", and the row passes.
def test_mmlu_example_row_passes(servers, run_cli):
    server = servers(contents=["The answer is B) Paris"])
    config = make_config(
        server.url,
        prompt={
            "system": "Answer the multiple choice question with a single letter.",
            "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}",
        },
        evaluation={
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "letter",
        },
        output_field="choice",
    )
    row = {
        "question": "What is the capital of France?",
        "a": "London",
        "b": "Paris",
        "c": "Berlin",
        "d": "Madrid",
        "answer": "B",
    }
    result = run_cli(config, [row])
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["result"] == {
        "passed": True,
        "extracted_answer": "B",
        "attempts": 1,
    }

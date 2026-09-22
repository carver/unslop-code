"""Part 2 extract methods: `letter` and `first_number`."""
import pytest

from conftest import make_config, make_multi_config
from mock_api import MockAPI, always, per_question

import rejector


# Spec: "letter: extract the first uppercase answer choice `A` through `D`;
# accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
# Context: New extract methods.
@pytest.mark.parametrize("text,expected", [
    ("A", "A"),
    ("(A)", "A"),
    ("A)", "A"),
    ("Answer: A", "A"),
    ("B", "B"),
    ("(C)", "C"),
    ("D)", "D"),
])
def test_letter_accepts_the_documented_forms(text, expected):
    assert rejector.extract_answer(text, "letter") == expected


# Spec example: "If the model returns `"The answer is B) Paris"`, `letter`
# extracts `"B"` and the row passes."
# Context: Examples, MMLU-style extraction.
def test_letter_extracts_b_from_the_spec_example():
    assert rejector.extract_answer("The answer is B) Paris", "letter") == "B"


def test_letter_takes_the_first_choice_when_several_appear():
    assert rejector.extract_answer("C) Berlin, not D) Madrid", "letter") == "C"


# T25: the `A` inside "Answer:" is part of a word, so it is not a choice.
def test_letter_ignores_capitals_that_are_part_of_a_word():
    assert rejector.extract_answer("Answer: C", "letter") == "C"
    assert rejector.extract_answer("Definitely D", "letter") == "D"


def test_letter_only_matches_a_through_d():
    assert rejector.extract_answer("E) none of these", "letter") is None


def test_letter_is_uppercase_only():
    assert rejector.extract_answer("the answer is b", "letter") is None


def test_letter_with_no_choice_returns_none():
    assert rejector.extract_answer("no idea", "letter") is None


# Spec: "first_number: extract the first integer or decimal in the response"
# Context: New extract methods.
@pytest.mark.parametrize("text,expected", [
    ("8", "8"),
    ("Score: 9 out of 10", "9"),
    ("3.5 seems right", "3.5"),
    ("first 1 then 2", "1"),
    ("I rate it 10/10", "10"),
])
def test_first_number_takes_the_leading_number(text, expected):
    assert rejector.extract_answer(text, "first_number") == expected


def test_first_number_with_no_number_returns_none():
    assert rejector.extract_answer("no digits here", "first_number") is None


# T26: the sign is part of the number, as it is for Part 1's `last_number`.
def test_first_number_includes_a_leading_minus():
    assert rejector.extract_answer("-4 then 9", "first_number") == "-4"


def test_first_number_and_last_number_differ():
    text = "step 1 gives 7 and finally 42"
    assert rejector.extract_answer(text, "first_number") == "1"
    assert rejector.extract_answer(text, "last_number") == "42"


# Spec: the new methods are usable from any evaluation block.
# Context: Examples, MMLU-style extraction -> exact_match with `letter`.
def test_letter_extract_drives_exact_match_end_to_end(run_tool):
    row = {"question": "What is the capital of France?", "a": "London",
           "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B"}
    evaluation = {"type": "exact_match", "answer_field": "answer",
                  "extract": "letter"}
    with MockAPI(always("The answer is B) Paris")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=evaluation,
                                   user="{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}"),
                       [row])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["extracted_answer"] == "B"
    assert run.rows[0]["result"]["passed"] is True


def test_letter_mismatch_fails_the_row(run_tool):
    row = {"question": "q", "a": "1", "b": "2", "c": "3", "d": "4", "answer": "B"}
    evaluation = {"type": "exact_match", "answer_field": "answer",
                  "extract": "letter"}
    with MockAPI(always("I pick C) three")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=evaluation),
                       [row])
    assert run.rows[0]["result"]["extracted_answer"] == "C"
    assert run.rows[0]["result"]["passed"] is False


def test_first_number_extract_drives_exact_match_end_to_end(run_tool):
    evaluation = {"type": "exact_match", "answer_field": "answer",
                  "extract": "first_number"}
    with MockAPI(always("7 is the count, not 9")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=evaluation),
                       [{"question": "q", "answer": "7"}])
    assert run.rows[0]["result"]["passed"] is True
    assert run.rows[0]["result"]["extracted_answer"] == "7"


def test_unknown_extract_method_still_exits_1(run_tool):
    evaluation = {"type": "exact_match", "answer_field": "answer",
                  "extract": "middle_number"}
    run = run_tool(make_config(evaluation=evaluation),
                   [{"question": "q", "answer": "7"}])
    assert run.returncode == 1
    assert run.stderr.strip()

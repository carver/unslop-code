"""The extract methods added in Part 2: `letter` and `first_number`."""

from __future__ import annotations

import pytest
from fake_server import FakeAPIServer, always
from conftest import base_config


def _extract(write_config, write_input, run_cli, method, content, row):
    """Run one greedy row with `method` and return its result object."""
    config_map = base_config("")
    config_map["task"]["evaluation"] = {
        "type": "exact_match", "answer_field": "answer", "extract": method,
    }
    with FakeAPIServer(always(content)) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([row]))
    return result.rows[0]["result"]


# Spec: "If the model returns "The answer is B) Paris", `letter` extracts "B"
# and the row passes."
def test_letter_extracts_the_worked_example(write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "letter",
        "The answer is B) Paris",
        {"question": "q", "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B"},
    )
    assert result["extracted_answer"] == "B"
    assert result["passed"] is True


# Spec: "letter: extract the first uppercase answer choice A through D; accept
# forms such as A, (A), A), or Answer: A"
@pytest.mark.parametrize(
    "content,expected",
    [
        ("A", "A"),
        ("(A)", "A"),
        ("A)", "A"),
        ("Answer: A", "A"),
        ("Answer: D.", "D"),
        ("  C  ", "C"),
        ("I think the correct option is B.", "B"),
    ],
)
def test_letter_accepts_the_documented_forms(content, expected, write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "letter", content, {"question": "q", "answer": expected}
    )
    assert result["extracted_answer"] == expected
    assert result["passed"] is True


# Spec: "letter: extract the *first* uppercase answer choice A through D"
def test_letter_takes_the_first_choice(write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "letter",
        "Between C) Berlin and B) Paris, I pick C",
        {"question": "q", "answer": "C"},
    )
    assert result["extracted_answer"] == "C"


# Spec: "letter: extract the first uppercase answer choice A through D" - E is
# not a choice, and letters inside words are not choices
def test_letter_ignores_non_choice_letters(write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "letter",
        "Every Estimate Fails",
        {"question": "q", "answer": "A"},
    )
    assert result["extracted_answer"] is None
    assert result["passed"] is False


# Spec: "letter: extract the first uppercase answer choice" - lowercase is not
# an uppercase choice
def test_letter_ignores_lowercase(write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "letter",
        "the answer is b) paris",
        {"question": "q", "answer": "B"},
    )
    assert result["extracted_answer"] is None


# Spec: "first_number: extract the first integer or decimal in the response"
@pytest.mark.parametrize(
    "content,expected",
    [
        ("8", "8"),
        ("Score: 7 out of 10", "7"),
        ("I rate this 8.5 overall, not 10", "8.5"),
        ("first 12 then 7 then 99", "12"),
        ("temperature fell to -8 from 4", "-8"),
    ],
)
def test_first_number_extraction(content, expected, write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "first_number", content,
        {"question": "q", "answer": expected},
    )
    assert result["extracted_answer"] == expected
    assert result["passed"] is True


# Spec: "first_number: extract the first integer or decimal" - nothing to
# extract when the response has no number
def test_first_number_without_a_number_is_null(write_config, write_input, run_cli):
    result = _extract(
        write_config, write_input, run_cli, "first_number", "no digits at all",
        {"question": "q", "answer": "8"},
    )
    assert result["extracted_answer"] is None
    assert result["passed"] is False

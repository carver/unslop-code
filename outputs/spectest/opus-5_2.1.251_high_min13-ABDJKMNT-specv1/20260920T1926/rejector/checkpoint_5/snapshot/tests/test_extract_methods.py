"""The `letter` and `first_number` extract methods added in Part 2."""

from __future__ import annotations

import pytest

from conftest import base_defaults, choice_task, task_rows
from fake_api import FakeAPI, always

from taskrunner.config import ConfigError, build_run_config
from taskrunner.evaluation import extract_answer


# Spec: "`letter`: extract the first uppercase answer choice `A` through `D`;
# accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
# Context: Evaluation Additions / New extract methods.
@pytest.mark.parametrize(
    "response,expected",
    [
        ("A", "A"),
        ("(A)", "A"),
        ("A)", "A"),
        ("Answer: A", "A"),
        ("B", "B"),
        ("(C)", "C"),
        ("D)", "D"),
        ("Answer: D", "D"),
    ],
)
def test_letter_accepts_the_documented_forms(response, expected):
    assert extract_answer(response, "letter") == expected


# Spec: "extract the first uppercase answer choice `A` through `D`"
# Context: the first such choice wins when several appear.
def test_letter_takes_the_first_choice():
    assert extract_answer("B is right, not C", "letter") == "B"


# Spec: "the first uppercase answer choice"
# Context: lowercase letters are not answer choices; see AMBIGUITIES T23.
def test_letter_ignores_lowercase_and_words():
    assert extract_answer("the answer is b", "letter") is None
    assert extract_answer("Alpha Beta Delta", "letter") is None


# Spec: "`A` through `D`"
# Context: letters outside the range are not choices.
def test_letter_ignores_letters_outside_the_range():
    assert extract_answer("The answer is E", "letter") is None


# Spec: "If the model returns `"The answer is B) Paris"`, `letter` extracts
# `"B"` and the row passes."
# Context: Examples / MMLU-style extraction.
def test_letter_extracts_from_the_spec_example():
    assert extract_answer("The answer is B) Paris", "letter") == "B"


# Spec: "`first_number`: extract the first integer or decimal in the response"
# Context: Evaluation Additions / New extract methods.
@pytest.mark.parametrize(
    "response,expected",
    [
        ("8", "8"),
        ("Score: 8\nAnother: 9", "8"),
        ("I rate it 7.5 out of 10", "7.5"),
        ("-3 degrees", "-3"),
    ],
)
def test_first_number_takes_the_first_number(response, expected):
    assert extract_answer(response, "first_number") == expected


def test_first_number_without_any_number():
    assert extract_answer("no digits here", "first_number") is None


# Spec: new extract methods are additions; Part 1 methods are unchanged.
# Context: "Existing behavior from Part 1 is unchanged unless stated here."
def test_part_one_extract_methods_still_work():
    assert extract_answer("#### 5\nthen 42", "last_number") == "42"
    assert extract_answer("a\nb\n", "last_line") == "b"
    assert extract_answer("whole text", "full") == "whole text"


# Spec: the extract method is validated as in Part 1.
# Context: Configuration.
def test_unknown_extract_method_is_rejected():
    with pytest.raises(ConfigError):
        build_run_config(
            {
                "defaults": base_defaults("http://localhost:8000"),
                "tasks": {"a": choice_task(evaluation={"type": "exact_match", "answer_field": "answer", "extract": "nope"})},
            },
            {},
        )


# Spec: "If the model returns `"The answer is B) Paris"`, `letter` extracts
# `"B"` and the row passes."
# Context: Examples / MMLU-style extraction, end to end.
def test_mmlu_example_row_passes_end_to_end(write_yaml, write_inputs, run_args, workdir):
    document = {
        "defaults": base_defaults("placeholder"),
        "tasks": {"mmlu": choice_task()},
    }
    row = {
        "question": "What is the capital of France?",
        "a": "London",
        "b": "Paris",
        "c": "Berlin",
        "d": "Madrid",
        "answer": "B",
    }
    with FakeAPI(responder=always("The answer is B) Paris")) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs({"mmlu": [row]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    assert result.returncode == 0
    rows = task_rows(result, "mmlu")
    assert rows[0]["result"]["extracted_answer"] == "B"
    assert rows[0]["result"]["passed"] is True

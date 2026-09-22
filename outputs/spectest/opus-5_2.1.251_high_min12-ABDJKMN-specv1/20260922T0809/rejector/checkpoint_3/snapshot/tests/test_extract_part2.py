"""Spec section: Part 2 / Evaluation Additions (new `extract` methods)."""
from __future__ import annotations

import copy

import pytest

from conftest import MMLU_TASK, base_config, multi_config
from mock_server import MockAPI, always


def _letter_run(run_tool, write_config, write_input, response, answer="B"):
    """Single-task Part 1 config using the new `letter` extract."""
    with MockAPI(always(response)) as api:
        cfg = write_config(base_config(
            api.url, evaluation={"type": "exact_match",
                                 "answer_field": "answer",
                                 "extract": "letter"}))
        data = write_input([{"question": "capital?", "answer": answer}])
        res = run_tool(cfg, data)
    return res


def _first_number_run(run_tool, write_config, write_input, response,
                      answer="8"):
    with MockAPI(always(response)) as api:
        cfg = write_config(base_config(
            api.url, evaluation={"type": "exact_match",
                                 "answer_field": "answer",
                                 "extract": "first_number"}))
        data = write_input([{"question": "q", "answer": answer}])
        res = run_tool(cfg, data)
    return res


# ---------------------------------------------------------------------------
# Phrase: "`letter`: extract the first uppercase answer choice `A` through `D`"
# Context: Part 2 / Evaluation Additions.  A bare letter response.
# ---------------------------------------------------------------------------
def test_letter_extracts_bare_letter(run_tool, write_config, write_input):
    res = _letter_run(run_tool, write_config, write_input, "B")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "B"
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
# Context: Part 2 / Evaluation Additions.  Each documented form in turn.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("response,expected", [
    ("A", "A"),
    ("(A)", "A"),
    ("A)", "A"),
    ("Answer: A", "A"),
    ("(C)", "C"),
    ("D)", "D"),
    ("Answer: D", "D"),
])
def test_letter_accepts_documented_forms(run_tool, write_config, write_input,
                                         response, expected):
    res = _letter_run(run_tool, write_config, write_input, response,
                      answer=expected)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == expected


# ---------------------------------------------------------------------------
# Phrase: "If the model returns `"The answer is B) Paris"`, `letter` extracts
#          `"B"` and the row passes."
# Context: Part 2 / Examples (MMLU-style extraction).
# ---------------------------------------------------------------------------
def test_letter_worked_example_from_spec(run_tool, write_config, write_input,
                                         workdir):
    with MockAPI(always("The answer is B) Paris")) as api:
        cfg = write_config(multi_config(api.url,
                                        {"mmlu": copy.deepcopy(MMLU_TASK)}))
        qa = write_input([{"question": "What is the capital of France?",
                           "a": "London", "b": "Paris", "c": "Berlin",
                           "d": "Madrid", "answer": "B"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    row = res.rows_for("mmlu")[0]
    assert row["result"]["extracted_answer"] == "B"
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "extract the *first* uppercase answer choice `A` through `D`"
# Context: Part 2 / Evaluation Additions.  With several candidates present the
# earliest wins (AMBIGUITIES T21).
# ---------------------------------------------------------------------------
def test_letter_takes_the_first_candidate(run_tool, write_config, write_input):
    res = _letter_run(run_tool, write_config, write_input,
                      "C) is wrong, and so is D. Final: A", answer="C")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "C"


# Context: same phrase - a letter embedded in an ordinary word is not a choice
# (AMBIGUITIES T21).
def test_letter_ignores_letters_inside_words(run_tool, write_config,
                                             write_input):
    res = _letter_run(run_tool, write_config, write_input,
                      "Berlin and Madrid are wrong. Answer: C", answer="C")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "C"


# Context: same phrase - `A` through `D` only; `E` is not an answer choice.
def test_letter_ignores_letters_outside_a_to_d(run_tool, write_config,
                                               write_input):
    res = _letter_run(run_tool, write_config, write_input,
                      "E) none of these, so B", answer="B")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "B"


# Context: same phrase - "uppercase" is literal; a lowercase letter is not a
# choice.
def test_letter_is_case_sensitive(run_tool, write_config, write_input):
    res = _letter_run(run_tool, write_config, write_input,
                      "i think it is b) paris, so B", answer="B")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "B"


# Context: same phrase - no choice at all yields a null extraction and a
# failing row (Part 1's "`null` when there is no ... output" rule).
def test_letter_with_no_choice_extracts_null(run_tool, write_config,
                                             write_input):
    res = _letter_run(run_tool, write_config, write_input,
                      "no idea at all", answer="B")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] is None
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Phrase: "`first_number`: extract the first integer or decimal in the
#          response"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_first_number_takes_the_first_integer(run_tool, write_config,
                                              write_input):
    res = _first_number_run(run_tool, write_config, write_input,
                            "8 out of 10", answer="8")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "8"
    assert res.rows[0]["result"]["passed"] is True


# Context: same phrase - a decimal counts as a number (AMBIGUITIES T22).
def test_first_number_takes_a_decimal(run_tool, write_config, write_input):
    res = _first_number_run(run_tool, write_config, write_input,
                            "score 7.5 then 9", answer="7.5")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "7.5"


# Context: same phrase - `first_number` and `last_number` differ only in which
# end of the response they read.
def test_first_number_differs_from_last_number(run_tool, write_config,
                                               write_input):
    res = _first_number_run(run_tool, write_config, write_input,
                            "3 then 4 then 5", answer="3")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "3"


# Context: same phrase - a leading minus sign is part of the literal
# (AMBIGUITIES T22).
def test_first_number_keeps_a_negative_sign(run_tool, write_config,
                                            write_input):
    res = _first_number_run(run_tool, write_config, write_input,
                            "delta -3 then 9", answer="-3")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "-3"


# Context: same phrase - a response with no number extracts null.
def test_first_number_with_no_number_extracts_null(run_tool, write_config,
                                                   write_input):
    res = _first_number_run(run_tool, write_config, write_input,
                            "no numbers here", answer="8")
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Phrase: "New extract methods" (the set of valid `extract` values grows)
# Context: Part 2 / Evaluation Additions.  Part 1 methods still validate, and
# an unknown method is still a config error.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["last_number", "last_line", "full",
                                    "letter", "first_number"])
def test_known_extract_methods_are_accepted(run_tool, write_config,
                                            write_input, method):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(
            api.url, evaluation={"type": "exact_match",
                                 "answer_field": "answer", "extract": method}))
        data = write_input([{"question": "q", "answer": "8"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res


def test_unknown_extract_method_still_exits_1(run_tool, write_config,
                                              write_input):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        evaluation={"type": "exact_match", "answer_field": "answer",
                    "extract": "second_number"}))
    data = write_input([{"question": "q", "answer": "8"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()

"""Part 2 extract methods: `letter` and `first_number`."""

import pytest

import fake_api


def _eval(**kw):
    base = {"type": "exact_match", "answer_field": "answer"}
    base.update(kw)
    return {"evaluation": base}


def _extract(run_task, response, method, answer="ZZZ"):
    """Run one greedy row and return its extracted_answer."""
    with fake_api.FakeAPI(fake_api.always(response)) as api:
        res = run_task(api, _eval(extract=method),
                       rows=[{"question": "q", "answer": answer}], check=0)
    return res.rows[0]


# ---------------------------------------------------------------------------
# Spec: "letter: extract the first uppercase answer choice A through D"
# Context: Evaluation Additions.  A bare letter.
# ---------------------------------------------------------------------------
def test_letter_extracts_a_bare_letter(run_task):
    row = _extract(run_task, "B", "letter")
    assert row["result"]["extracted_answer"] == "B"


# ---------------------------------------------------------------------------
# Spec: "accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
# Context: Evaluation Additions.  Parenthesised form.
# ---------------------------------------------------------------------------
def test_letter_accepts_parenthesised_form(run_task):
    row = _extract(run_task, "(C)", "letter")
    assert row["result"]["extracted_answer"] == "C"


# ---------------------------------------------------------------------------
# Spec: "accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
# Context: Evaluation Additions.  Trailing-paren form.
# ---------------------------------------------------------------------------
def test_letter_accepts_trailing_paren_form(run_task):
    row = _extract(run_task, "D) Madrid", "letter")
    assert row["result"]["extracted_answer"] == "D"


# ---------------------------------------------------------------------------
# Spec: "accept forms such as `A`, `(A)`, `A)`, or `Answer: A`"
# Context: Evaluation Additions.  Labelled form.  AMBIGUITIES T28 — the "A"
# inside the word "Answer" is not itself a choice.
# ---------------------------------------------------------------------------
def test_letter_accepts_answer_label_form(run_task):
    row = _extract(run_task, "Answer: A", "letter")
    assert row["result"]["extracted_answer"] == "A"


# ---------------------------------------------------------------------------
# Spec: "extract the first uppercase answer choice A through D"
# Context: Evaluation Additions.  AMBIGUITIES T28 — letters embedded in words
# are skipped, so a leading capitalised word does not win.
# ---------------------------------------------------------------------------
def test_letter_skips_letters_inside_words(run_task):
    row = _extract(run_task, "Definitely the choice is C.", "letter")
    assert row["result"]["extracted_answer"] == "C"


# ---------------------------------------------------------------------------
# Spec: "extract the first uppercase answer choice A through D"
# Context: Evaluation Additions.  "first" — an earlier choice wins.
# ---------------------------------------------------------------------------
def test_letter_takes_the_first_choice_when_several_appear(run_task):
    row = _extract(run_task, "between A and D, I pick D", "letter")
    assert row["result"]["extracted_answer"] == "A"


# ---------------------------------------------------------------------------
# Spec: "the first uppercase answer choice A through D"
# Context: Evaluation Additions.  Lowercase is not an answer choice.
# ---------------------------------------------------------------------------
def test_letter_ignores_lowercase(run_task):
    row = _extract(run_task, "the answer is b, i mean B", "letter")
    assert row["result"]["extracted_answer"] == "B"


# ---------------------------------------------------------------------------
# Spec: "the first uppercase answer choice A through D"
# Context: Evaluation Additions.  E is outside the A-D range.
# ---------------------------------------------------------------------------
def test_letter_ignores_letters_outside_a_to_d(run_task):
    row = _extract(run_task, "E then B", "letter")
    assert row["result"]["extracted_answer"] == "B"


# ---------------------------------------------------------------------------
# Spec: "letter: extract the first uppercase answer choice A through D"
# Context: Evaluation Additions.  AMBIGUITIES T18 — nothing to extract means a
# failed evaluation with a null extracted_answer.
# ---------------------------------------------------------------------------
def test_letter_with_no_choice_fails_the_row(run_task):
    row = _extract(run_task, "no choice here", "letter")
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Spec (Examples): '{"question": "What is the capital of France?", ...,
#        "answer": "B"}' with model output "The answer is B) Paris" ->
#        'letter extracts "B" and the row passes'
# Context: Examples, MMLU-style extraction.  The worked example end to end.
# ---------------------------------------------------------------------------
def test_mmlu_example_extracts_b_and_passes(run_task):
    rows = [{"question": "What is the capital of France?", "a": "London",
             "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B"}]
    with fake_api.FakeAPI(fake_api.always("The answer is B) Paris")) as api:
        res = run_task(api, dict(_eval(extract="letter"),
                                 prompt={"user": "{question}\n\nA) {a}\nB) "
                                                 "{b}\nC) {c}\nD) {d}"}),
                       rows=rows, check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "B"
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "first_number: extract the first integer or decimal in the response"
# Context: Evaluation Additions.  Integer.
# ---------------------------------------------------------------------------
def test_first_number_extracts_an_integer(run_task):
    row = _extract(run_task, "score 8 out of 10", "first_number", answer="8")
    assert row["result"]["extracted_answer"] == "8"
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "first_number: extract the first integer or decimal"
# Context: Evaluation Additions.  Decimal.
# ---------------------------------------------------------------------------
def test_first_number_extracts_a_decimal(run_task):
    row = _extract(run_task, "7.5 then 9", "first_number", answer="7.5")
    assert row["result"]["extracted_answer"] == "7.5"


# ---------------------------------------------------------------------------
# Spec: "extract the *first* integer or decimal"
# Context: Evaluation Additions.  Contrast with Part 1's `last_number`.
# ---------------------------------------------------------------------------
def test_first_number_is_not_last_number(run_task):
    row = _extract(run_task, "1 2 3", "first_number", answer="1")
    assert row["result"]["extracted_answer"] == "1"


# ---------------------------------------------------------------------------
# Spec: "first_number: extract the first integer or decimal"
# Context: Evaluation Additions.  AMBIGUITIES T29 — a leading minus sign is
# part of the number, matching Part 1's `last_number`.
# ---------------------------------------------------------------------------
def test_first_number_keeps_a_leading_minus(run_task):
    row = _extract(run_task, "temperature -3 degrees", "first_number",
                   answer="-3")
    assert row["result"]["extracted_answer"] == "-3"


# ---------------------------------------------------------------------------
# Spec: "first_number: extract the first integer or decimal in the response"
# Context: Evaluation Additions.  No number -> nothing extracted, row fails.
# ---------------------------------------------------------------------------
def test_first_number_with_no_number_fails_the_row(run_task):
    row = _extract(run_task, "no digits at all", "first_number")
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Spec: "New extract methods"
# Context: Evaluation Additions.  The Part 1 methods are still accepted.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["last_number", "last_line", "full",
                                    "letter", "first_number"])
def test_all_extract_methods_are_accepted(run_task, method):
    with fake_api.FakeAPI(fake_api.always("A 1")) as api:
        res = run_task(api, _eval(extract=method),
                       rows=[{"question": "q", "answer": "A 1"}], check=0)
    assert res.returncode == 0


# ---------------------------------------------------------------------------
# Spec: "New extract methods: letter ... first_number"
# Context: Evaluation Additions.  An unknown method is still a config error.
# ---------------------------------------------------------------------------
def test_unknown_extract_method_is_an_error(run_task):
    with fake_api.FakeAPI(fake_api.always("A")) as api:
        res = run_task(api, _eval(extract="middle_number"), check=None)
    assert res.returncode == 1

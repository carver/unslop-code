"""Evaluation types and extract methods."""

import pytest

import fake_api


def _eval(**kw):
    base = {"type": "exact_match", "answer_field": "answer", "extract": "full"}
    base.update(kw)
    return {"evaluation": base}


# ---------------------------------------------------------------------------
# Spec: "exact_match: extract an answer from the response and compare it to
#        the configured answer_field from the input row"
# Context: Evaluation types.  Matching extraction -> passed true.
# ---------------------------------------------------------------------------
def test_exact_match_passes_when_extraction_equals_answer_field(run_task):
    with fake_api.FakeAPI(fake_api.always("2 + 3 = 5\n#### 5")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "5"}], check=0)
    assert res.rows[0]["result"]["passed"] is True
    assert res.rows[0]["result"]["extracted_answer"] == "5"


# ---------------------------------------------------------------------------
# Spec: "exact_match: ... compare it to the configured answer_field"
# Context: Evaluation types.  Mismatch -> passed false.
# ---------------------------------------------------------------------------
def test_exact_match_fails_when_extraction_differs(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 7")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "5"}], check=0)
    assert res.rows[0]["result"]["passed"] is False
    assert res.rows[0]["result"]["extracted_answer"] == "7"


# ---------------------------------------------------------------------------
# Spec: "exact_match" is exact — not a substring test.
# Context: Evaluation types.  "15" must not match answer "5".
# ---------------------------------------------------------------------------
def test_exact_match_is_not_substring_match(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 15")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "5"}], check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "compare it to the configured answer_field from the input row"
# Context: AMBIGUITIES T9 — surrounding whitespace is stripped and non-string
# row values are coerced to text.
# ---------------------------------------------------------------------------
def test_exact_match_strips_and_coerces(run_task):
    with fake_api.FakeAPI(fake_api.always("  8  \n")) as api:
        res = run_task(api, _eval(extract="full"),
                       rows=[{"question": "q", "answer": 8}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "contains: response text must contain the answer_field value as a
#        substring"
# Context: Evaluation types.  Substring present -> passed.
# ---------------------------------------------------------------------------
def test_contains_passes_on_substring(run_task):
    with fake_api.FakeAPI(fake_api.always("The capital is Paris, France.")) as api:
        res = run_task(api, _eval(type="contains"),
                       rows=[{"question": "q", "answer": "Paris"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "contains: response text must contain the answer_field value"
# Context: Evaluation types.  Absent substring -> failed.
# ---------------------------------------------------------------------------
def test_contains_fails_when_absent(run_task):
    with fake_api.FakeAPI(fake_api.always("The capital is Berlin.")) as api:
        res = run_task(api, _eval(type="contains"),
                       rows=[{"question": "q", "answer": "Paris"}], check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "regex: response text must match the configured pattern"
# Context: Evaluation types.  Matching pattern -> passed.
# ---------------------------------------------------------------------------
def test_regex_passes_on_match(run_task):
    with fake_api.FakeAPI(fake_api.always("blah\n#### 42")) as api:
        res = run_task(api, {"evaluation": {"type": "regex",
                                            "pattern": r"####\s*\d+",
                                            "answer_field": None,
                                            "extract": None}},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "regex: response text must match the configured pattern"
# Context: Evaluation types.  Non-matching pattern -> failed.
# ---------------------------------------------------------------------------
def test_regex_fails_without_match(run_task):
    with fake_api.FakeAPI(fake_api.always("no answer here")) as api:
        res = run_task(api, {"evaluation": {"type": "regex",
                                            "pattern": r"####\s*\d+",
                                            "answer_field": None,
                                            "extract": None}},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "regex: response text must match the configured pattern"
# Context: Evaluation types.  A match anywhere in the text counts (search, not
# fullmatch) — the pattern in the spec's own idiom is a fragment.
# ---------------------------------------------------------------------------
def test_regex_matches_anywhere_in_text(run_task):
    with fake_api.FakeAPI(fake_api.always("prefix ANSWER: 7 suffix")) as api:
        res = run_task(api, {"evaluation": {"type": "regex",
                                            "pattern": r"ANSWER: \d",
                                            "answer_field": None,
                                            "extract": None}},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "last_number: use the last integer or decimal in the response"
# Context: Extract methods.  The *last* number wins.
# ---------------------------------------------------------------------------
def test_last_number_takes_the_last_integer(run_task):
    with fake_api.FakeAPI(fake_api.always("5 + 3 = 8\n#### 8")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "8"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "8"


# ---------------------------------------------------------------------------
# Spec: "last_number: use the last integer or decimal"
# Context: Extract methods.  Decimals are captured whole, not truncated at the
# decimal point.
# ---------------------------------------------------------------------------
def test_last_number_captures_decimals(run_task):
    with fake_api.FakeAPI(fake_api.always("the cost is 3.50 dollars")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "3.50"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "3.50"
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "last_number: use the last integer or decimal" (AMBIGUITIES T10)
# Context: Extract methods.  A leading minus is part of the number.
# ---------------------------------------------------------------------------
def test_last_number_keeps_negative_sign(run_task):
    with fake_api.FakeAPI(fake_api.always("result: -12")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "-12"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "-12"


# ---------------------------------------------------------------------------
# Spec: "last_number" (AMBIGUITIES T18)
# Context: Extract methods.  No number at all -> null extraction, failed.
# ---------------------------------------------------------------------------
def test_last_number_with_no_number_is_null_and_fails(run_task):
    with fake_api.FakeAPI(fake_api.always("no digits here")) as api:
        res = run_task(api, _eval(extract="last_number"),
                       rows=[{"question": "q", "answer": "5"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] is None
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "last_line: use the last non-empty line"
# Context: Extract methods.  Trailing blank lines are skipped.
# ---------------------------------------------------------------------------
def test_last_line_skips_trailing_blank_lines(run_task):
    with fake_api.FakeAPI(fake_api.always("step one\nstep two\nParis\n\n  \n")) as api:
        res = run_task(api, _eval(extract="last_line"),
                       rows=[{"question": "q", "answer": "Paris"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "Paris"
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "full: use the entire response text"
# Context: Extract methods.  The whole body is the comparison value.
# ---------------------------------------------------------------------------
def test_full_uses_entire_response(run_task):
    with fake_api.FakeAPI(fake_api.always("line one\nline two")) as api:
        res = run_task(api, _eval(extract="full"),
                       rows=[{"question": "q", "answer": "line one\nline two"}],
                       check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "line one\nline two"
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: extract is optional in the validation rules (AMBIGUITIES T4)
# Context: Extract methods.  Omitted extract behaves like `full`.
# ---------------------------------------------------------------------------
def test_extract_defaults_to_full(run_task):
    with fake_api.FakeAPI(fake_api.always("Paris")) as api:
        res = run_task(api, _eval(extract=None),
                       rows=[{"question": "q", "answer": "Paris"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "Paris"
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "result.extracted_answer is the extracted comparison value"
# Context: AMBIGUITIES T5/T6 — the extract step feeds every evaluation type,
# so `contains` reports the extracted value it searched.
# ---------------------------------------------------------------------------
def test_contains_reports_extracted_comparison_value(run_task):
    with fake_api.FakeAPI(fake_api.always("intro\nthe answer is Paris")) as api:
        res = run_task(api, _eval(type="contains", extract="last_line"),
                       rows=[{"question": "q", "answer": "Paris"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] == "the answer is Paris"
    assert res.rows[0]["result"]["passed"] is True

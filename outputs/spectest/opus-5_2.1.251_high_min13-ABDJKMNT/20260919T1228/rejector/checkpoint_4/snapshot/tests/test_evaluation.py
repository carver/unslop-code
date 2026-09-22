"""Evaluation types, exercised directly against the evaluation module."""

from __future__ import annotations

from rejector_lib.config import EvaluationConfig
from rejector_lib.evaluation import evaluate_response


def _check(text, **eval_kwargs):
    row = eval_kwargs.pop("row", {"answer": "8"})
    config = EvaluationConfig(**eval_kwargs)
    return evaluate_response(text, config, row)


# Spec: "exact_match: extract an answer from the response and compare it to
# the configured answer_field from the input row".
def test_exact_match_passes_on_equal_extracted_answer():
    passed, extracted = _check(
        "2+6 = 8\n#### 8", type="exact_match", answer_field="answer", extract="last_number"
    )
    assert (passed, extracted) == (True, "8")


# Spec: "exact_match ... compare it to the configured answer_field".
def test_exact_match_fails_on_different_answer():
    passed, extracted = _check(
        "#### 9", type="exact_match", answer_field="answer", extract="last_number"
    )
    assert (passed, extracted) == (False, "9")


# Spec: "exact_match" against a row whose answer is a JSON number, not a string.
def test_exact_match_compares_non_string_answer_values():
    passed, _ = _check(
        "#### 8",
        type="exact_match",
        answer_field="answer",
        extract="last_number",
        row={"answer": 8},
    )
    assert passed is True


# Spec: "exact_match" is an exact comparison -- no numeric normalization. (T3)
def test_exact_match_does_not_normalize_decimals():
    passed, _ = _check(
        "#### 8.0", type="exact_match", answer_field="answer", extract="last_number"
    )
    assert passed is False


# Spec: "exact_match" when extraction found nothing -- there is no value to
# compare, so the row fails and extracted_answer is null.
def test_exact_match_without_an_extractable_answer_fails():
    passed, extracted = _check(
        "no numbers", type="exact_match", answer_field="answer", extract="last_number"
    )
    assert (passed, extracted) == (False, None)


# Spec: "contains: response text must contain the answer_field value as a
# substring".
def test_contains_passes_when_answer_is_a_substring():
    passed, _ = _check("the total is 8 apples", type="contains", answer_field="answer")
    assert passed is True


# Spec: "contains: response text must contain the answer_field value".
def test_contains_fails_when_answer_is_absent():
    passed, _ = _check("the total is nine", type="contains", answer_field="answer")
    assert passed is False


# Spec: "contains" matches against the response text, not an extracted value,
# so it passes even with an extract method that would select something else.
def test_contains_matches_full_text_despite_extract_method():
    passed, _ = _check(
        "8 apples\nno digits on this line",
        type="contains",
        answer_field="answer",
        extract="last_line",
    )
    assert passed is True


# Spec: "regex: response text must match the configured pattern". (T7: search)
def test_regex_passes_when_the_pattern_is_found():
    passed, _ = _check("thinking...\n#### 42", type="regex", pattern=r"####\s*\d+")
    assert passed is True


# Spec: "regex: response text must match the configured pattern".
def test_regex_fails_when_the_pattern_is_absent():
    passed, _ = _check("no final answer", type="regex", pattern=r"####\s*\d+")
    assert passed is False


# Spec: "result.extracted_answer is the extracted comparison value" -- for
# contains/regex the configured extract method (default `full`) is used. (T2)
def test_extracted_answer_uses_extract_method_for_non_exact_types():
    _, extracted = _check("answer line\n#### 7", type="regex", pattern=r"####")
    assert extracted == "answer line\n#### 7"
    _, extracted = _check(
        "answer line\n#### 7", type="regex", pattern=r"####", extract="last_number"
    )
    assert extracted == "7"

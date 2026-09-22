"""Spec section: Evaluation types and Extract methods."""
from __future__ import annotations

import pytest

from conftest import base_config
from mock_server import MockAPI, always


def _row(run_tool, write_config, write_input, content, cfg_kwargs, row):
    with MockAPI(always(content)) as api:
        cfg = write_config(base_config(api.url, **cfg_kwargs))
        data = write_input([row])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    return res.rows[0]


# ---------------------------------------------------------------------------
# Phrase: "exact_match: extract an answer from the response and compare it to
#          the configured answer_field from the input row"
# Context: Evaluation types.
# ---------------------------------------------------------------------------
def test_exact_match_passes(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "Let me solve this step by step.\n5 + 3 = 8\n#### 8",
               {}, {"question": "q", "answer": "8"})
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "8"


def test_exact_match_fails(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input, "#### 7",
               {}, {"question": "q", "answer": "8"})
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] == "7"


# Context: same phrase - the answer_field name is configurable.
def test_exact_match_uses_configured_answer_field(run_tool, write_config,
                                                  write_input):
    row = _row(run_tool, write_config, write_input, "#### 8",
               {"evaluation": {"answer_field": "gold"}},
               {"question": "q", "gold": "8", "answer": "999"})
    assert row["result"]["passed"] is True


# Context: same phrase - a numeric answer field in the row still compares.
def test_exact_match_with_numeric_row_value(run_tool, write_config,
                                            write_input):
    row = _row(run_tool, write_config, write_input, "#### 8",
               {}, {"question": "q", "answer": 8})
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "contains: response text must contain the answer_field value as a
#          substring"
# Context: Evaluation types.
# ---------------------------------------------------------------------------
def test_contains_passes(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "The capital of France is Paris, of course.",
               {"evaluation": {"type": "contains", "answer_field": "answer",
                               "extract": None}},
               {"question": "q", "answer": "Paris"})
    assert row["result"]["passed"] is True


def test_contains_fails(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "The capital of France is Lyon.",
               {"evaluation": {"type": "contains", "answer_field": "answer",
                               "extract": None}},
               {"question": "q", "answer": "Paris"})
    assert row["result"]["passed"] is False


# Context: same phrase - substring, not equality, and it may appear anywhere.
def test_contains_matches_substring_anywhere(run_tool, write_config,
                                             write_input):
    row = _row(run_tool, write_config, write_input,
               "prefix-ANSWER42-suffix",
               {"evaluation": {"type": "contains", "answer_field": "answer",
                               "extract": None}},
               {"question": "q", "answer": "ANSWER42"})
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "regex: response text must match the configured pattern"
# Context: Evaluation types.  (Ambiguity T4: `re.search` semantics.)
# ---------------------------------------------------------------------------
def test_regex_passes(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "blah blah\n#### 42",
               {"evaluation": {"type": "regex", "pattern": r"####\s*\d+",
                               "answer_field": None, "extract": None}},
               {"question": "q"})
    assert row["result"]["passed"] is True


def test_regex_fails(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "no final marker here",
               {"evaluation": {"type": "regex", "pattern": r"####\s*\d+",
                               "answer_field": None, "extract": None}},
               {"question": "q"})
    assert row["result"]["passed"] is False


# Context (ambiguity T4): the pattern is searched for, not anchored.
def test_regex_is_unanchored(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "lots of text before the target token",
               {"evaluation": {"type": "regex", "pattern": r"target",
                               "answer_field": None, "extract": None}},
               {"question": "q"})
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "last_number: use the last integer or decimal in the response"
# Context: Extract methods.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("content,expected", [
    ("2 + 3 = 5\n#### 5", "5"),
    ("first 1 then 2 then 3", "3"),
    ("the value is 3.14", "3.14"),
    ("temperature is -7", "-7"),
    ("#### 8", "8"),
])
def test_last_number_extraction(run_tool, write_config, write_input,
                                content, expected):
    row = _row(run_tool, write_config, write_input, content, {},
               {"question": "q", "answer": expected})
    assert row["result"]["extracted_answer"] == expected
    assert row["result"]["passed"] is True


# Context: same phrase - no number in the response means nothing to extract.
def test_last_number_with_no_number(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input, "no digits at all",
               {}, {"question": "q", "answer": "5"})
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Phrase: "last_line: use the last non-empty line"
# Context: Extract methods.
# ---------------------------------------------------------------------------
def test_last_line_extraction(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input,
               "step one\nstep two\nParis\n\n   \n",
               {"evaluation": {"extract": "last_line"}},
               {"question": "q", "answer": "Paris"})
    assert row["result"]["extracted_answer"] == "Paris"
    assert row["result"]["passed"] is True


def test_last_line_single_line_response(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input, "only line",
               {"evaluation": {"extract": "last_line"}},
               {"question": "q", "answer": "only line"})
    assert row["result"]["extracted_answer"] == "only line"


# ---------------------------------------------------------------------------
# Phrase: "full: use the entire response text"
# Context: Extract methods.
# ---------------------------------------------------------------------------
def test_full_extraction(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input, "line one\nline two",
               {"evaluation": {"extract": "full"}},
               {"question": "q", "answer": "line one\nline two"})
    assert row["result"]["extracted_answer"] == "line one\nline two"
    assert row["result"]["passed"] is True


# Context (ambiguity T11): `extract` defaults to `full` when omitted.
def test_extract_defaults_to_full(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input, "exactly this",
               {"evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": None}},
               {"question": "q", "answer": "exactly this"})
    assert row["result"]["extracted_answer"] == "exactly this"
    assert row["result"]["passed"] is True


# Context (ambiguity T3): contains/regex still report the extracted value.
def test_extracted_answer_reported_for_contains(run_tool, write_config,
                                                write_input):
    row = _row(run_tool, write_config, write_input, "answer: 42",
               {"evaluation": {"type": "contains", "answer_field": "answer",
                               "extract": "last_number"}},
               {"question": "q", "answer": "42"})
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "42"


# Context (ambiguity T5): exact_match is a string comparison, so a differently
# formatted number does not match.
def test_exact_match_is_string_comparison(run_tool, write_config, write_input):
    row = _row(run_tool, write_config, write_input, "#### 8.0",
               {}, {"question": "q", "answer": "8"})
    assert row["result"]["extracted_answer"] == "8.0"
    assert row["result"]["passed"] is False

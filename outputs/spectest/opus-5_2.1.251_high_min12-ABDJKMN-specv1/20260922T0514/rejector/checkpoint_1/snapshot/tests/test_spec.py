"""Tests derived phrase-by-phrase from the spec.

Each section comment quotes the spec phrase under test plus the minimal
context needed to read it.
"""
import json
import re
import subprocess
import sys
import time

import pytest
import yaml

from conftest import REJECTOR, completion, make_config

ROW = {"question": "What is 2 + 3?", "answer": "5"}


# ---------------------------------------------------------------------------
# Deliverable
# "The tool starts with:
#   python rejector.py run --config <path> --input <path> --output <path>"
# ---------------------------------------------------------------------------

def test_run_subcommand_with_required_flags_succeeds(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW])
    assert r.code == 0, r.stderr
    assert len(r.rows) == 1


# Deliverable: "--output <path>: JSONL output file, created or overwritten"
def test_output_file_is_created(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW])
    assert r.out_path.exists()
    assert r.out_path.read_text().endswith("\n")


def test_existing_output_file_is_overwritten(run_cli, echo_api):
    cfg = make_config(echo_api.url)
    r1 = run_cli(cfg, [ROW])
    stale = r1.out_path
    stale.write_text("STALE LINE\n" * 20)
    proc = subprocess.run(
        [sys.executable, str(REJECTOR), "run",
         "--config", str(stale.parent / "case1.yaml"),
         "--input", str(stale.parent / "case1.jsonl"),
         "--output", str(stale)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "STALE" not in stale.read_text()
    assert len([l for l in stale.read_text().splitlines() if l.strip()]) == 1


# Deliverable: "Required flags: --config, --input, --output"
@pytest.mark.parametrize("drop", ["--config", "--input", "--output"])
def test_missing_required_flag_is_an_error(tmp_path, echo_api, drop):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(make_config(echo_api.url)))
    inp = tmp_path / "i.jsonl"
    inp.write_text(json.dumps(ROW) + "\n")
    out = tmp_path / "o.jsonl"
    pairs = {"--config": str(cfg), "--input": str(inp), "--output": str(out)}
    argv = [sys.executable, str(REJECTOR), "run"]
    for flag, val in pairs.items():
        if flag != drop:
            argv += [flag, val]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    # T14: usage errors exit 1 (spec enumerates only 0 and 1).
    assert proc.returncode == 1
    assert proc.stderr.strip()


# Deliverable: "Exit codes: 0: success"
def test_exit_code_zero_on_success(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW])
    assert r.code == 0


# Deliverable: "Exit codes: 1: configuration or input error"
def test_exit_code_one_for_unreadable_config(tmp_path, echo_api):
    inp = tmp_path / "i.jsonl"
    inp.write_text(json.dumps(ROW) + "\n")
    proc = subprocess.run(
        [sys.executable, str(REJECTOR), "run", "--config", str(tmp_path / "nope.yaml"),
         "--input", str(inp), "--output", str(tmp_path / "o.jsonl")],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_exit_code_one_for_missing_input_file(tmp_path, echo_api):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(make_config(echo_api.url)))
    proc = subprocess.run(
        [sys.executable, str(REJECTOR), "run", "--config", str(cfg),
         "--input", str(tmp_path / "nope.jsonl"), "--output", str(tmp_path / "o.jsonl")],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_malformed_yaml_config_exits_one(run_cli, echo_api):
    r = run_cli(None, [ROW], config_text="task: [unclosed\n  : :\n")
    assert r.code == 1
    assert r.stderr.strip()


# ---------------------------------------------------------------------------
# Deliverable: optional overrides
# "Optional overrides replace the corresponding config values when provided"
# ---------------------------------------------------------------------------

# "--api-url <string>"
def test_api_url_override_replaces_config_value(run_cli, api):
    good = api(lambda b, i: (200, completion("#### 5")))
    cfg = make_config("http://127.0.0.1:1/unused")
    r = run_cli(cfg, [ROW], args=["--api-url", good.url])
    assert r.code == 0, r.stderr
    assert good.call_count == 1


# "--model <string>"
def test_model_override_is_sent_in_request(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5", model="override-model")))
    r = run_cli(make_config(srv.url), [ROW], args=["--model", "override-model"])
    assert r.code == 0, r.stderr
    assert srv.bodies[0]["model"] == "override-model"


# "--max-tokens <int>"
def test_max_tokens_override_is_sent_in_request(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW], args=["--max-tokens", "99"])
    assert r.code == 0, r.stderr
    assert echo_api.bodies[0]["max_tokens"] == 99


# "--temperature <float>" (with a scheme that honours it)
def test_temperature_override_is_sent_in_request(run_cli, echo_api):
    cfg = make_config(echo_api.url, generation={"scheme": "sample", "temperature": 0.1,
                                                "max_tokens": 256})
    r = run_cli(cfg, [ROW], args=["--temperature", "0.9"])
    assert r.code == 0, r.stderr
    assert echo_api.bodies[0]["temperature"] == pytest.approx(0.9)


# "--scheme <greedy|sample|rejection>"
def test_scheme_override_switches_scheme(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = make_config(srv.url, generation={"scheme": "greedy", "temperature": 0.7,
                                           "max_tokens": 256, "n": 3})
    r = run_cli(cfg, [ROW], args=["--scheme", "sample"])
    assert r.code == 0, r.stderr
    # sample honours the configured temperature instead of forcing 0.0
    assert srv.bodies[0]["temperature"] == pytest.approx(0.7)


def test_invalid_scheme_override_exits_one(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW], args=["--scheme", "beam"])
    assert r.code == 1
    assert r.stderr.strip()


# "--n <int>"
def test_n_override_changes_rejection_attempt_budget(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 0")))  # never matches answer 5
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 256, "n": 2})
    r = run_cli(cfg, [ROW], args=["--n", "4"])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 4
    assert srv.call_count == 4


# "--rpm <int>"
def test_rpm_override_is_accepted(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW], args=["--rpm", "120"])
    assert r.code == 0, r.stderr


# ---------------------------------------------------------------------------
# Configuration
# "prompt.system and prompt.user use {field} placeholders resolved from each
#  input row."
# ---------------------------------------------------------------------------

def test_placeholders_are_resolved_from_the_row(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = make_config(srv.url, prompt={"system": "Answer in {lang}.", "user": "Q: {question}"})
    r = run_cli(cfg, [{"question": "What is 2 + 3?", "answer": "5", "lang": "French"}])
    assert r.code == 0, r.stderr
    msgs = srv.bodies[0]["messages"]
    assert msgs[0]["content"] == "Answer in French."
    assert msgs[1]["content"] == "Q: What is 2 + 3?"


def test_non_string_field_values_render(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 7")))
    cfg = make_config(srv.url, prompt={"system": "s", "user": "{a} and {b}"},
                      evaluation=None)
    r = run_cli(cfg, [{"a": 7, "b": True}])
    assert r.code == 0, r.stderr
    assert srv.bodies[0]["messages"][1]["content"] == "7 and True"


# "If a placeholder references a missing field, exit with code 1 and print an
#  error to stderr naming the row index and missing field."
def test_missing_placeholder_field_exits_one_naming_row_and_field(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [{"text": "hello"}])
    assert r.code == 1
    assert "0" in r.stderr
    assert "question" in r.stderr


def test_missing_placeholder_field_on_later_row_names_that_row(run_cli, echo_api):
    rows = [ROW, ROW, {"answer": "1"}]
    r = run_cli(make_config(echo_api.url), rows)
    assert r.code == 1
    assert re.search(r"\b2\b", r.stderr), r.stderr
    assert "question" in r.stderr


# T11: validation happens before any request is issued.
def test_missing_placeholder_field_issues_no_requests(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [{"text": "hello"}])
    assert r.code == 1
    assert echo_api.call_count == 0


def test_missing_system_placeholder_field_also_errors(run_cli, echo_api):
    cfg = make_config(echo_api.url, prompt={"system": "Use {style}.", "user": "{question}"})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert "style" in r.stderr


# ---------------------------------------------------------------------------
# Generation behavior
# "greedy: force temperature to 0.0; n is ignored"
# ---------------------------------------------------------------------------

def test_greedy_forces_temperature_zero(run_cli, echo_api):
    cfg = make_config(echo_api.url,
                      generation={"scheme": "greedy", "temperature": 0.9, "max_tokens": 256})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert echo_api.bodies[0]["temperature"] == 0.0


def test_greedy_ignores_n(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 0")))  # fails evaluation
    cfg = make_config(srv.url, generation={"scheme": "greedy", "max_tokens": 256, "n": 5})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert srv.call_count == 1
    assert r.rows[0]["result"]["attempts"] == 1


# "sample: temperature must be > 0; n is ignored"
def test_sample_uses_configured_temperature(run_cli, echo_api):
    cfg = make_config(echo_api.url,
                      generation={"scheme": "sample", "temperature": 0.7, "max_tokens": 256})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert echo_api.bodies[0]["temperature"] == pytest.approx(0.7)


def test_sample_with_zero_temperature_exits_one(run_cli, echo_api):
    cfg = make_config(echo_api.url,
                      generation={"scheme": "sample", "temperature": 0.0, "max_tokens": 256})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


def test_sample_ignores_n(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 0")))
    cfg = make_config(srv.url, generation={"scheme": "sample", "temperature": 0.5,
                                           "max_tokens": 256, "n": 4})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert srv.call_count == 1
    assert r.rows[0]["result"]["attempts"] == 1


# "rejection: temperature must be > 0; make up to n attempts and keep the first
#  passing response"
def test_rejection_requires_positive_temperature(run_cli, echo_api):
    cfg = make_config(echo_api.url, generation={"scheme": "rejection", "temperature": 0.0,
                                                "max_tokens": 256, "n": 3})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


def test_rejection_keeps_first_passing_response(run_cli, api):
    def responder(body, i):
        return (200, completion("#### 5" if i == 2 else "#### 1"))
    srv = api(responder)
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 256, "n": 5})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 3
    assert srv.call_count == 3  # T16: stops as soon as one passes


def test_rejection_stops_at_first_attempt_when_it_passes(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 256, "n": 5})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert srv.call_count == 1
    assert r.rows[0]["result"]["attempts"] == 1


# "if all attempts fail, output null with \"passed\": false"
def test_rejection_exhausted_yields_null_output_and_passed_false(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 9")))
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 256, "n": 5})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["attempts"] == 5
    assert isinstance(row["meta"], list) and len(row["meta"]) == 5
    assert srv.call_count == 5


# ---------------------------------------------------------------------------
# Evaluation types
# "exact_match: extract an answer from the response and compare it to the
#  configured answer_field from the input row"
# ---------------------------------------------------------------------------

def test_exact_match_passes_when_extracted_equals_answer_field(run_cli, api):
    srv = api(lambda b, i: (200, completion("Let me solve.\n5 + 3 = 8\n#### 8")))
    cfg = make_config(srv.url)
    r = run_cli(cfg, [{"question": "q", "answer": "8"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True
    assert r.rows[0]["result"]["extracted_answer"] == "8"


def test_exact_match_fails_when_values_differ(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 7")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "8"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False
    assert r.rows[0]["result"]["extracted_answer"] == "7"


def test_exact_match_compares_against_numeric_answer_field(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 8")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": 8}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# "contains: response text must contain the answer_field value as a substring"
def test_contains_passes_on_substring(run_cli, api):
    srv = api(lambda b, i: (200, completion("The capital is Paris, France.")))
    cfg = make_config(srv.url, evaluation={"type": "contains", "answer_field": "answer"})
    r = run_cli(cfg, [{"question": "q", "answer": "Paris"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


def test_contains_fails_when_absent(run_cli, api):
    srv = api(lambda b, i: (200, completion("The capital is Lyon.")))
    cfg = make_config(srv.url, evaluation={"type": "contains", "answer_field": "answer"})
    r = run_cli(cfg, [{"question": "q", "answer": "Paris"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False


def test_contains_checks_whole_response_not_just_extract(run_cli, api):
    # answer appears on an earlier line; extract=last_line must not narrow the check
    srv = api(lambda b, i: (200, completion("Paris is the answer.\nDone.")))
    cfg = make_config(srv.url, evaluation={"type": "contains", "answer_field": "answer",
                                           "extract": "last_line"})
    r = run_cli(cfg, [{"question": "q", "answer": "Paris"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# "regex: response text must match the configured pattern"
def test_regex_passes_when_pattern_matches(run_cli, api):
    srv = api(lambda b, i: (200, completion("blah blah\n#### 42")))
    cfg = make_config(srv.url, evaluation={"type": "regex", "pattern": r"####\s*\d+"})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


def test_regex_fails_when_pattern_absent(run_cli, api):
    srv = api(lambda b, i: (200, completion("no marker here")))
    cfg = make_config(srv.url, evaluation={"type": "regex", "pattern": r"####\s*\d+"})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False


# T10: regex is an unanchored search over the response text.
def test_regex_matches_anywhere_in_response(run_cli, api):
    srv = api(lambda b, i: (200, completion("preamble\nANSWER: yes\ntrailer")))
    cfg = make_config(srv.url, evaluation={"type": "regex", "pattern": r"ANSWER: yes"})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


def test_invalid_regex_pattern_exits_one(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation={"type": "regex", "pattern": "([unclosed"})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 1
    assert r.stderr.strip()


def test_unknown_evaluation_type_exits_one(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation={"type": "bleu", "answer_field": "answer"})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


# ---------------------------------------------------------------------------
# Extract methods
# "last_number: use the last integer or decimal in the response"
# ---------------------------------------------------------------------------

def test_last_number_picks_the_final_number(run_cli, api):
    srv = api(lambda b, i: (200, completion("First 12, then 7, finally\n#### 42")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "42"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "42"


def test_last_number_handles_decimals(run_cli, api):
    srv = api(lambda b, i: (200, completion("the speed is 30.5 mph")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "30.5"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "30.5"
    assert r.rows[0]["result"]["passed"] is True


def test_last_number_with_no_number_in_response(run_cli, api):
    # No number at all: nothing to compare, so the row cannot pass.
    srv = api(lambda b, i: (200, completion("no digits here")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "8"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False


# "last_line: use the last non-empty line"
def test_last_line_uses_last_non_empty_line(run_cli, api):
    srv = api(lambda b, i: (200, completion("reasoning\nmore reasoning\nParis\n\n  \n")))
    cfg = make_config(srv.url, evaluation={"type": "exact_match", "answer_field": "answer",
                                           "extract": "last_line"})
    r = run_cli(cfg, [{"question": "q", "answer": "Paris"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "Paris"
    assert r.rows[0]["result"]["passed"] is True


# "full: use the entire response text"
def test_full_uses_entire_response(run_cli, api):
    srv = api(lambda b, i: (200, completion("exactly this")))
    cfg = make_config(srv.url, evaluation={"type": "exact_match", "answer_field": "answer",
                                           "extract": "full"})
    r = run_cli(cfg, [{"question": "q", "answer": "exactly this"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "exactly this"
    assert r.rows[0]["result"]["passed"] is True


def test_unknown_extract_method_exits_one(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation={"type": "exact_match", "answer_field": "answer",
                                                "extract": "first_number"})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


# ---------------------------------------------------------------------------
# Validation rules
# "evaluation is required for rejection and optional otherwise"
# ---------------------------------------------------------------------------

def test_rejection_without_evaluation_exits_one(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation=None,
                      generation={"scheme": "rejection", "temperature": 0.8,
                                  "max_tokens": 256, "n": 3})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


@pytest.mark.parametrize("gen", [
    {"scheme": "greedy", "max_tokens": 256},
    {"scheme": "sample", "temperature": 0.5, "max_tokens": 256},
])
def test_evaluation_optional_for_greedy_and_sample(run_cli, echo_api, gen):
    cfg = make_config(echo_api.url, evaluation=None, generation=gen)
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr


# "exact_match and contains require answer_field"
@pytest.mark.parametrize("etype", ["exact_match", "contains"])
def test_answer_field_required(run_cli, echo_api, etype):
    cfg = make_config(echo_api.url, evaluation={"type": etype})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


# "regex requires pattern and does not require answer_field"
def test_regex_requires_pattern(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation={"type": "regex"})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


def test_regex_does_not_require_answer_field(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = make_config(srv.url, evaluation={"type": "regex", "pattern": "####"})
    r = run_cli(cfg, [{"question": "q"}])  # row has no answer field either
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# "if evaluation is omitted for greedy or sample, result.passed must be null"
def test_passed_is_null_without_evaluation(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation=None)
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is None
    assert r.rows[0]["result"]["extracted_answer"] is None


# "Invalid configuration exits with code 1 and a descriptive message on stderr."
@pytest.mark.parametrize("mutate", [
    {"api_url": None},
    {"model": None},
    {"prompt": None},
    {"output_field": None},
])
def test_missing_required_config_key_exits_one(run_cli, echo_api, mutate):
    cfg = make_config(echo_api.url, **mutate)
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


def test_config_without_task_key_exits_one(run_cli, echo_api):
    r = run_cli({"name": "x"}, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


def test_unknown_scheme_in_config_exits_one(run_cli, echo_api):
    cfg = make_config(echo_api.url, generation={"scheme": "beam", "max_tokens": 10})
    r = run_cli(cfg, [ROW])
    assert r.code == 1
    assert r.stderr.strip()


# ---------------------------------------------------------------------------
# API Contract
# "Send POST requests to {api_url}/v1/chat/completions"
# ---------------------------------------------------------------------------

def test_requests_go_to_chat_completions_path(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW])
    assert r.code == 0, r.stderr
    assert echo_api.requests[0]["path"] == "/v1/chat/completions"


def test_trailing_slash_in_api_url_is_handled(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url + "/"), [ROW])
    assert r.code == 0, r.stderr
    assert echo_api.requests[0]["path"] == "/v1/chat/completions"


# Request body: {"model", "messages": [system, user], "temperature", "max_tokens"}
def test_request_body_shape(run_cli, echo_api):
    cfg = make_config(echo_api.url,
                      generation={"scheme": "greedy", "temperature": 0.0, "max_tokens": 512})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    body = echo_api.bodies[0]
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512
    assert body["messages"] == [
        {"role": "system", "content": "Solve the math problem. Final answer after ####."},
        {"role": "user", "content": "What is 2 + 3?"},
    ]


def test_request_is_json_encoded(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [ROW])
    assert r.code == 0, r.stderr
    ctype = echo_api.requests[0]["headers"].get("Content-Type", "")
    assert "json" in ctype.lower()


# "The API returns standard OpenAI-style chat completions" — content, usage and
# finish_reason are read from the response.
def test_response_fields_flow_into_output_and_meta(run_cli, api):
    payload = completion("text body", prompt_tokens=45, completion_tokens=120,
                         finish_reason="length")
    srv = api(lambda b, i: (200, payload))
    cfg = make_config(srv.url, evaluation=None)
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] == {"solution": "text body"}
    assert row["meta"]["prompt_tokens"] == 45
    assert row["meta"]["completion_tokens"] == 120
    assert row["meta"]["total_tokens"] == 165
    assert row["meta"]["finish_reason"] == "length"
    assert row["meta"]["model"] == "gpt-4"


# "If a request receives an HTTP 5xx, retry it up to 3 total requests."
def test_5xx_is_retried_and_succeeds_on_third_request(run_cli, api):
    def responder(body, i):
        if i < 2:
            return (503, {"error": "overloaded"})
        return (200, completion("#### 5"))
    srv = api(responder)
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    assert srv.call_count == 3
    assert r.rows[0]["output"] == {"solution": "#### 5"}
    assert r.rows[0]["result"]["passed"] is True


def test_retry_budget_is_three_total_requests(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    assert srv.call_count == 3


# "After the third failure, treat that row as failed, emit null output for it,
#  count it as failed in the summary, and continue."
def test_row_fails_after_exhausted_retries(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] is None
    assert row["result"]["extracted_answer"] is None
    assert r.summary["failed"] == 1
    assert r.summary["passed"] == 0


def test_processing_continues_after_a_failed_row(run_cli, api):
    rows = [{"question": "a", "answer": "1"},
            {"question": "b", "answer": "2"},
            {"question": "c", "answer": "3"}]

    def responder(body, i):
        if body["messages"][-1]["content"] == "b":
            return (500, {"error": "boom"})
        return (200, completion("#### " + {"a": "1", "c": "3"}[body["messages"][-1]["content"]]))
    srv = api(responder)
    r = run_cli(make_config(srv.url), rows)
    assert r.code == 0, r.stderr
    out = r.rows
    assert len(out) == 3
    assert out[0]["output"] is not None
    assert out[1]["output"] is None
    assert out[2]["output"] is not None
    assert r.summary["passed"] == 2
    assert r.summary["failed"] == 1


# "Retry requests count toward total_api_calls, but for greedy and sample rows
#  they do not increase the logical result.attempts count."
def test_retries_count_in_api_calls_but_not_attempts(run_cli, api):
    def responder(body, i):
        if i < 2:
            return (502, {"error": "bad gateway"})
        return (200, completion("#### 5"))
    srv = api(responder)
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 1
    assert r.summary["total_api_calls"] == 3


# T4: a hard failure still reports the documented attempt count for greedy.
def test_failed_greedy_row_reports_one_attempt(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 1


# T2: no successful response means no metadata object.
def test_meta_is_null_when_no_response_was_obtained(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["meta"] is None


# T12: 4xx is not retried.
def test_4xx_is_not_retried(run_cli, api):
    srv = api(lambda b, i: (400, {"error": "bad request"}))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    assert srv.call_count == 1
    assert r.rows[0]["output"] is None


# T3: a hard HTTP failure abandons the rejection row.
def test_rejection_row_abandoned_on_hard_http_failure(run_cli, api):
    def responder(body, i):
        if i == 0:
            return (200, completion("#### 1"))  # fails evaluation
        return (500, {"error": "boom"})
    srv = api(responder)
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 256, "n": 5})
    r = run_cli(cfg, [{"question": "q", "answer": "5"}])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["attempts"] == 2
    assert srv.call_count == 1 + 3  # attempt 1, then 3 requests for attempt 2


# An unreachable API is a runtime failure, not a config/input error: exit 0
# with every row failed. (Exit 1 is reserved for "configuration or input error".)
def test_unreachable_api_fails_rows_but_exits_zero(run_cli, tmp_path):
    cfg = make_config("http://127.0.0.1:9")
    r = run_cli(cfg, [ROW], timeout=180)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] is None
    assert r.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Input
# "The input file is JSONL with one object per line."
# ---------------------------------------------------------------------------

def test_each_input_line_produces_a_row(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1")))
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(5)]
    r = run_cli(make_config(srv.url), rows)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 5


def test_blank_lines_are_ignored(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1")))
    text = json.dumps({"question": "a", "answer": "1"}) + "\n\n" + \
        json.dumps({"question": "b", "answer": "1"}) + "\n\n"
    r = run_cli(make_config(srv.url), None, input_text=text)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 2


def test_malformed_json_line_exits_one(run_cli, echo_api):
    text = json.dumps(ROW) + "\n{not json}\n"
    r = run_cli(make_config(echo_api.url), None, input_text=text)
    assert r.code == 1
    assert r.stderr.strip()


def test_empty_input_produces_empty_output_and_zero_summary(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [])
    assert r.code == 0, r.stderr
    assert r.rows == []
    s = r.summary
    assert s["total"] == 0
    assert s["passed"] == 0
    assert s["failed"] == 0
    assert s["total_api_calls"] == 0


# "When the configured evaluation uses answer_field, each row must also contain
#  that field."
def test_row_missing_answer_field_exits_one(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [{"question": "q"}])
    assert r.code == 1
    assert "answer" in r.stderr
    assert "0" in r.stderr


def test_row_missing_answer_field_issues_no_requests(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [{"question": "q"}])
    assert r.code == 1
    assert echo_api.call_count == 0


# ---------------------------------------------------------------------------
# Output
# "Write one JSON object per input row, in the same order as the input."
# ---------------------------------------------------------------------------

def test_output_rows_are_in_input_order_under_concurrency(run_cli, api):
    rows = [{"question": "q%02d" % k, "answer": str(k)} for k in range(20)]

    def responder(body, i):
        q = body["messages"][-1]["content"]
        k = int(q[1:])
        # Make earlier rows slow so a naive implementation would reorder them.
        time.sleep(0.4 if k < 5 else 0.02)
        return (200, completion("#### %d" % k))
    srv = api(responder)
    r = run_cli(make_config(srv.url), rows)
    assert r.code == 0, r.stderr
    out = r.rows
    assert [o["input"]["question"] for o in out] == [r_["question"] for r_ in rows]
    # each row kept its own response
    for k, o in enumerate(out):
        assert o["output"]["solution"] == "#### %d" % k
        assert o["result"]["passed"] is True


# "input is the original row, unchanged"
def test_input_is_echoed_unchanged(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    row = {"question": "What is 2 + 3?", "answer": "5", "extra": {"nested": [1, 2]}, "id": 7}
    r = run_cli(make_config(srv.url), [row])
    assert r.code == 0, r.stderr
    assert r.rows[0]["input"] == row


# "output is an object with one key named by output_field"
def test_output_key_is_named_by_output_field(run_cli, api):
    srv = api(lambda b, i: (200, completion("hello there")))
    cfg = make_config(srv.url, output_field="completion", evaluation=None)
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"completion": "hello there"}


# "result.passed is true for a passing evaluation, false for a failing
#  evaluation, and null when no evaluation is configured"
def test_result_passed_true_false_null(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    passed = run_cli(make_config(srv.url), [{"question": "q", "answer": "5"}])
    failed = run_cli(make_config(srv.url), [{"question": "q", "answer": "6"}])
    none = run_cli(make_config(srv.url, evaluation=None), [{"question": "q"}])
    assert passed.rows[0]["result"]["passed"] is True
    assert failed.rows[0]["result"]["passed"] is False
    assert none.rows[0]["result"]["passed"] is None


# "result.extracted_answer is the extracted comparison value, or null when
#  there is no evaluation or no output"
def test_extracted_answer_null_without_evaluation(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    r = run_cli(make_config(srv.url, evaluation=None), [{"question": "q"}])
    assert r.rows[0]["result"]["extracted_answer"] is None


def test_extracted_answer_null_when_output_is_null(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.rows[0]["output"] is None
    assert r.rows[0]["result"]["extracted_answer"] is None


# T9: with contains/regex the extract method still drives extracted_answer.
def test_extracted_answer_present_for_contains(run_cli, api):
    srv = api(lambda b, i: (200, completion("reasoning\nParis")))
    cfg = make_config(srv.url, evaluation={"type": "contains", "answer_field": "answer",
                                           "extract": "last_line"})
    r = run_cli(cfg, [{"question": "q", "answer": "Paris"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "Paris"


# "result.attempts is the number of logical generation attempts for that row:
#  1 for greedy and sample, 1..n for rejection"
@pytest.mark.parametrize("gen", [
    {"scheme": "greedy", "max_tokens": 64},
    {"scheme": "sample", "temperature": 0.5, "max_tokens": 64},
])
def test_attempts_is_one_for_greedy_and_sample(run_cli, api, gen):
    srv = api(lambda b, i: (200, completion("#### 5")))
    r = run_cli(make_config(srv.url, generation=gen), [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 1


@pytest.mark.parametrize("pass_on,expected", [(0, 1), (1, 2), (2, 3)])
def test_rejection_attempts_within_one_to_n(run_cli, api, pass_on, expected):
    srv = api(lambda b, i: (200, completion("#### 5" if i == pass_on else "#### 0")))
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 64, "n": 3})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == expected


# "meta is a single metadata object for one-attempt rows; for rejection
#  sampling with multiple attempts it is a list with one metadata object per
#  attempt"
def test_meta_is_object_for_single_attempt_rows(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    r = run_cli(make_config(srv.url), [ROW])
    assert isinstance(r.rows[0]["meta"], dict)


# T1: a rejection row that passes immediately is still a one-attempt row.
def test_meta_is_object_for_rejection_row_with_one_attempt(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 64, "n": 3})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert isinstance(r.rows[0]["meta"], dict)


def test_meta_is_list_with_one_entry_per_rejection_attempt(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5" if i == 2 else "#### 0")))
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 64, "n": 4})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    meta = r.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 3
    assert all(isinstance(m, dict) for m in meta)


# meta keys, per the documented per-row shape
def test_meta_keys(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    r = run_cli(make_config(srv.url), [ROW])
    meta = r.rows[0]["meta"]
    assert set(meta) == {"model", "prompt_tokens", "completion_tokens", "total_tokens",
                         "latency_ms", "finish_reason"}


# "meta.latency_ms is wall-clock latency for that API call"
def test_latency_ms_reflects_server_delay(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")), delay=0.3)
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    lat = r.rows[0]["meta"]["latency_ms"]
    assert isinstance(lat, (int, float))
    assert 250 <= lat <= 3000


# Per-row shape: exactly the four documented top-level keys
def test_row_top_level_keys(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    r = run_cli(make_config(srv.url), [ROW])
    assert set(r.rows[0]) == {"input", "output", "result", "meta"}
    assert set(r.rows[0]["result"]) == {"passed", "extracted_answer", "attempts"}


# ---------------------------------------------------------------------------
# Summary
# "After processing finishes, print one JSON summary object to stdout"
# ---------------------------------------------------------------------------

def test_summary_is_a_single_json_object_on_stdout(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == 1
    s = json.loads(lines[0])
    assert set(s) == {"total", "passed", "failed", "total_prompt_tokens",
                      "total_completion_tokens", "total_api_calls",
                      "elapsed_seconds", "throughput_rpm"}


# "total: input row count"
def test_summary_total_is_row_count(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1")))
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(7)]
    r = run_cli(make_config(srv.url), rows)
    assert r.summary["total"] == 7


# "passed: rows where result.passed is true"
# "failed: rows where result.passed is false or output is null"
def test_summary_passed_and_failed_counts(run_cli, api):
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(4)]

    def responder(body, i):
        k = int(body["messages"][-1]["content"][1:])
        return (200, completion("#### 1" if k < 3 else "#### 2"))
    srv = api(responder)
    r = run_cli(make_config(srv.url), rows)
    assert r.code == 0, r.stderr
    s = r.summary
    assert s["passed"] == 3
    assert s["failed"] == 1
    assert s["passed"] + s["failed"] == s["total"]


# "when no evaluation is configured, treat successful API rows as passed"
def test_summary_counts_unevaluated_successful_rows_as_passed(run_cli, api):
    srv = api(lambda b, i: (200, completion("anything")))
    rows = [{"question": "a"}, {"question": "b"}]
    cfg = make_config(srv.url, evaluation=None)
    r = run_cli(cfg, rows)
    assert r.code == 0, r.stderr
    assert r.summary["passed"] == 2
    assert r.summary["failed"] == 0


def test_summary_counts_null_output_rows_as_failed_without_evaluation(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    cfg = make_config(srv.url, evaluation=None)
    r = run_cli(cfg, [{"question": "a"}])
    assert r.code == 0, r.stderr
    assert r.summary["failed"] == 1
    assert r.summary["passed"] == 0


# "total_prompt_tokens" / "total_completion_tokens"
def test_summary_token_totals(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1", prompt_tokens=10, completion_tokens=4)))
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(3)]
    r = run_cli(make_config(srv.url), rows)
    assert r.summary["total_prompt_tokens"] == 30
    assert r.summary["total_completion_tokens"] == 12


# "total_api_calls: all HTTP requests, including retries and rejection attempts"
def test_summary_api_calls_include_retries_and_rejection_attempts(run_cli, api):
    # row 0: 2 x 5xx then success on the 3rd request, then fails eval -> attempt 2 passes
    def responder(body, i):
        if i < 2:
            return (503, {"error": "busy"})
        if i == 2:
            return (200, completion("#### 0"))   # attempt 1 fails evaluation
        return (200, completion("#### 5"))       # attempt 2 passes
    srv = api(responder)
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 64, "n": 3})
    r = run_cli(cfg, [ROW])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 2
    assert srv.call_count == 4
    assert r.summary["total_api_calls"] == 4


# "elapsed_seconds: wall-clock time from first request to last response,
#  rounded to 1 decimal place"
def test_summary_elapsed_seconds_rounded_to_one_decimal(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")), delay=0.5)
    r = run_cli(make_config(srv.url), [ROW])
    assert r.code == 0, r.stderr
    e = r.summary["elapsed_seconds"]
    assert round(e, 1) == e
    assert 0.4 <= e <= 5.0


# "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to 1 decimal"
def test_summary_throughput_matches_formula(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1")), delay=0.2)
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(10)]
    r = run_cli(make_config(srv.url), rows)
    assert r.code == 0, r.stderr
    s = r.summary
    expected = round(s["total_api_calls"] / s["elapsed_seconds"] * 60, 1)
    # the tool divides by the unrounded elapsed time, so allow rounding slack
    assert s["throughput_rpm"] == pytest.approx(expected, rel=0.15)


# ---------------------------------------------------------------------------
# Throughput
# "The tool must issue requests concurrently ... Target at least 80% of the
#  configured rpm."
# ---------------------------------------------------------------------------

def test_requests_are_issued_concurrently(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1")), delay=0.4)
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(12)]
    t0 = time.time()
    r = run_cli(make_config(srv.url, rpm=60), rows)
    elapsed = time.time() - t0
    assert r.code == 0, r.stderr
    assert srv.max_inflight > 1, "requests were issued sequentially"
    assert elapsed < 12 * 0.4 * 0.6, "wall clock looks sequential: %.2fs" % elapsed


def test_throughput_reaches_at_least_80_percent_of_rpm(run_cli, api):
    # Server takes 0.5s per request; 60 rpm can only be reached concurrently.
    srv = api(lambda b, i: (200, completion("#### 1")), delay=0.5)
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(20)]
    r = run_cli(make_config(srv.url, rpm=60), rows)
    assert r.code == 0, r.stderr
    assert r.summary["throughput_rpm"] >= 0.8 * 60


def test_concurrency_scales_with_rpm(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 1")), delay=0.5)
    rows = [{"question": "q%d" % k, "answer": "1"} for k in range(30)]
    r = run_cli(make_config(srv.url, rpm=300), rows)
    assert r.code == 0, r.stderr
    assert srv.max_inflight >= 8, "in-flight work did not scale: %d" % srv.max_inflight


# ---------------------------------------------------------------------------
# Examples
# The spec's greedy example: config, one input row, and the exact output row.
# ---------------------------------------------------------------------------

def test_spec_greedy_example(run_cli, api):
    srv = api(lambda b, i: (200, completion("2 + 3 = 5\n#### 5", prompt_tokens=30,
                                            completion_tokens=10)))
    cfg = make_config(srv.url)  # the spec's example config verbatim
    r = run_cli(cfg, [{"question": "What is 2 + 3?", "answer": "5"}])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert row["meta"]["model"] == "gpt-4"
    assert row["meta"]["prompt_tokens"] == 30
    assert row["meta"]["completion_tokens"] == 10
    assert row["meta"]["total_tokens"] == 40
    assert row["meta"]["finish_reason"] == "stop"


# "Rejection example with n: 3: if the first two responses fail evaluation and
#  the third passes, the output row records attempts: 3, keeps the third
#  response as output, and includes three metadata entries."
def test_spec_rejection_example(run_cli, api):
    texts = ["#### 1", "#### 2", "#### 42"]
    srv = api(lambda b, i: (200, completion(texts[i])))
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.9,
                                           "max_tokens": 256, "n": 3})
    r = run_cli(cfg, [{"question": "q", "answer": "42"}])
    assert r.code == 0, r.stderr
    row = r.rows[0]
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"]["passed"] is True
    assert len(row["meta"]) == 3


# "If a prompt template references {question} and row 0 is {"text": "hello"},
#  exit with code 1 and print an error to stderr naming row 0 and missing
#  field question."
def test_spec_missing_field_example(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), [{"text": "hello"}])
    assert r.code == 1
    assert "question" in r.stderr
    assert "0" in r.stderr


# ---------------------------------------------------------------------------
# Interpretation checks recorded in AMBIGUITIES.md
# ---------------------------------------------------------------------------

# T13: "if evaluation is omitted ... result.passed must be null" holds even for
# a row whose API calls all failed (the summary still counts it as failed).
def test_passed_stays_null_for_failed_row_without_evaluation(run_cli, api):
    srv = api(lambda b, i: (500, {"error": "boom"}))
    cfg = make_config(srv.url, evaluation=None)
    r = run_cli(cfg, [{"question": "a"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is None
    assert r.rows[0]["output"] is None


# T2/T1: a rejection row that collected some metadata before a hard HTTP
# failure keeps the metadata it has, in list form (2+ attempts).
def test_rejection_hard_failure_keeps_collected_meta(run_cli, api):
    def responder(body, i):
        return (200, completion("#### 1")) if i == 0 else (500, {"error": "boom"})
    srv = api(responder)
    cfg = make_config(srv.url, generation={"scheme": "rejection", "temperature": 0.8,
                                           "max_tokens": 64, "n": 4})
    r = run_cli(cfg, [{"question": "q", "answer": "5"}])
    assert r.code == 0, r.stderr
    meta = r.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 1


# T7: "last integer or decimal" includes a leading sign, and a grouped numeral
# is one number.
def test_last_number_handles_negative_values(run_cli, api):
    srv = api(lambda b, i: (200, completion("the balance is -42")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "-42"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == "-42"
    assert r.rows[0]["result"]["passed"] is True


def test_last_number_handles_thousands_separators(run_cli, api):
    srv = api(lambda b, i: (200, completion("total is 1,234")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "1234"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# T8: exact_match falls back to a numeric comparison for numerically equal text.
def test_exact_match_numeric_equivalence(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 8.0")))
    r = run_cli(make_config(srv.url), [{"question": "q", "answer": "8"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


def test_exact_match_ignores_surrounding_whitespace(run_cli, api):
    srv = api(lambda b, i: (200, completion("Paris  \n")))
    cfg = make_config(srv.url, evaluation={"type": "exact_match", "answer_field": "answer",
                                           "extract": "full"})
    r = run_cli(cfg, [{"question": "q", "answer": "Paris"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# T15: defaults — a config omitting temperature/n/rpm still runs under greedy.
def test_minimal_greedy_config_runs(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = {"task": {"name": "t", "api_url": srv.url, "model": "m",
                    "prompt": {"user": "{question}"},
                    "generation": {"scheme": "greedy"},
                    "output_field": "solution"}}
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] == {"solution": "#### 5"}
    # no system prompt configured -> only the user message is sent
    assert [m["role"] for m in srv.bodies[0]["messages"]] == ["user"]


# T15: scheme defaults to greedy when generation is omitted entirely.
def test_generation_block_optional_defaults_to_greedy(run_cli, api):
    srv = api(lambda b, i: (200, completion("#### 5")))
    cfg = {"task": {"name": "t", "api_url": srv.url, "model": "m",
                    "prompt": {"user": "{question}"},
                    "output_field": "solution"}}
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert srv.bodies[0]["temperature"] == 0.0
    assert srv.bodies[0]["max_tokens"] == 512

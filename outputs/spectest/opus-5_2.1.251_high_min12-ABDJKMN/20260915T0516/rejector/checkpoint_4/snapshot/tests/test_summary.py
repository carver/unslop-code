"""The JSON summary printed to stdout after processing."""
import json
import threading

import pytest

from conftest import make_config
from mock_api import MockAPI, always, chat_response, status


def per_row_sequence(mapping, default=("#### 0",), **kw):
    counts = {}
    lock = threading.Lock()

    def responder(payload, i):
        user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        with lock:
            k = counts.get(user, 0)
            counts[user] = k + 1
        seq = mapping.get(user, default)
        item = seq[k] if k < len(seq) else seq[-1]
        if isinstance(item, int):
            return item, {"error": "boom"}
        return 200, chat_response(item, **kw)
    return responder


# Spec: "After processing finishes, print one JSON summary object to stdout."
# Context: Output.
def test_stdout_is_exactly_one_json_object(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    lines = [l for l in run.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    assert isinstance(json.loads(lines[0]), dict)


def test_summary_has_all_documented_keys(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    # Part 2 adds `tasks` to every summary (see AMBIGUITIES T23); Part 3 adds
    # the solution counts (T53).
    assert set(run.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm", "tasks", "total_solutions",
        "avg_solutions_per_input"}


# Spec: "total: input row count"
def test_total_is_the_input_row_count(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(7)]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["total"] == 7


# Spec: "passed: rows where result.passed is true"
def test_passed_counts_rows_with_passing_evaluation(run_tool):
    responder = per_row_sequence({"a": ["#### 5"], "b": ["#### 9"],
                                  "c": ["#### 5"]})
    rows = [{"question": c, "answer": "5"} for c in "abc"]
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["passed"] == 2
    assert run.summary["failed"] == 1


# Spec: "when no evaluation is configured, treat successful API rows as passed"
def test_passed_counts_successful_rows_when_no_evaluation(run_tool):
    rows = [{"question": "q%d" % i} for i in range(4)]
    with MockAPI(always("anything at all")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["passed"] == 4
    assert run.summary["failed"] == 0
    assert all(r["result"]["passed"] is None for r in run.rows)


# Spec: "failed: rows where result.passed is false or output is null"
def test_failed_counts_evaluation_failures_and_null_outputs(run_tool):
    responder = per_row_sequence({"a": ["#### 5"], "b": ["#### 9"], "c": [500]})
    rows = [{"question": c, "answer": "5"} for c in "abc"]
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["passed"] == 1
    assert run.summary["failed"] == 2
    assert run.summary["passed"] + run.summary["failed"] == run.summary["total"]


# Spec: total_prompt_tokens / total_completion_tokens
# Context: Output summary example.
def test_token_totals_sum_across_rows(run_tool):
    responder = lambda p, i: (200, chat_response("#### 5", prompt_tokens=45,
                                                 completion_tokens=120))
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(3)]
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["total_prompt_tokens"] == 135
    assert run.summary["total_completion_tokens"] == 360


def test_token_totals_include_every_rejection_attempt(run_tool):
    responder = per_row_sequence({"q": ["#### 0", "#### 0", "#### 42"]},
                                 prompt_tokens=10, completion_tokens=2)
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, scheme="rejection",
                                   temperature=0.7, n=3),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert run.summary["total_prompt_tokens"] == 30
    assert run.summary["total_completion_tokens"] == 6


# Spec: "total_api_calls: all HTTP requests, including retries and rejection
#        attempts"
def test_total_api_calls_counts_plain_requests(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(5)]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 5
    assert run.summary["total_api_calls"] == api.call_count


def test_total_api_calls_includes_rejection_attempts(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="rejection",
                                   temperature=0.7, n=4),
                       [{"question": "q", "answer": "42"},
                        {"question": "q2", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 8
    assert run.summary["total_api_calls"] == api.call_count


def test_total_api_calls_includes_retries(run_tool):
    responder = per_row_sequence({"a": [500, "#### 5"], "b": ["#### 5"]})
    rows = [{"question": "a", "answer": "5"}, {"question": "b", "answer": "5"}]
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 3


# Spec: "elapsed_seconds: wall-clock time from first request to last response,
#        rounded to 1 decimal place"
def test_elapsed_seconds_rounded_to_one_decimal(run_tool):
    with MockAPI(always("#### 5"), service_seconds=0.3) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    elapsed = run.summary["elapsed_seconds"]
    assert isinstance(elapsed, float)
    assert round(elapsed, 1) == elapsed
    assert 0.2 <= elapsed <= 10.0


# Spec: "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to 1
#        decimal place"
def test_throughput_rpm_matches_its_formula(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(8)]
    with MockAPI(always("#### 5"), service_seconds=0.2) as api:
        run = run_tool(make_config(api_url=api.url, rpm=600), rows)
    assert run.returncode == 0, run.stderr
    s = run.summary
    expected = round(s["total_api_calls"] / s["elapsed_seconds"] * 60, 1)
    assert s["throughput_rpm"] == pytest.approx(expected, rel=0.05)
    assert round(s["throughput_rpm"], 1) == s["throughput_rpm"]


def test_summary_counts_are_integers(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    s = run.summary
    for key in ("total", "passed", "failed", "total_prompt_tokens",
                "total_completion_tokens", "total_api_calls"):
        assert isinstance(s[key], int), key

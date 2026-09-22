"""The JSON summary printed to stdout after processing."""

import json

import pytest

import fake_api


# ---------------------------------------------------------------------------
# Spec: "After processing finishes, print one JSON summary object to stdout"
# Context: Output.  Exactly the eight documented keys.
# ---------------------------------------------------------------------------
def test_summary_has_the_documented_keys(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    assert set(res.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm",
    }


# ---------------------------------------------------------------------------
# Spec: "print one JSON summary object to stdout"
# Context: Output.  Stdout is a single JSON object (the output rows go to the
# --output file, not to stdout).
# ---------------------------------------------------------------------------
def test_stdout_is_only_the_summary(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, rows=[{"question": "a", "answer": "5"},
                                  {"question": "b", "answer": "5"}], check=0)
    assert json.loads(res.stdout.strip())["total"] == 2


# ---------------------------------------------------------------------------
# Spec: "total: input row count"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_total_is_the_input_row_count(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(7)]
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, rows=rows, check=0)
    assert res.summary["total"] == 7


# ---------------------------------------------------------------------------
# Spec: "passed: rows where result.passed is true"
#       "failed: rows where result.passed is false or output is null"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_passed_and_failed_counts_with_evaluation(run_task):
    script = {"a": ["#### 5"], "b": ["#### 5"], "c": ["#### 9"]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, rows=[{"question": "a", "answer": "5"},
                                  {"question": "b", "answer": "5"},
                                  {"question": "c", "answer": "5"}], check=0)
    assert res.summary["passed"] == 2
    assert res.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Spec: "passed: ... when no evaluation is configured, treat successful API
#        rows as passed"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_no_evaluation_counts_successful_rows_as_passed(run_task):
    with fake_api.FakeAPI(fake_api.always("anything")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "a"}, {"question": "b"}], check=0)
    assert res.summary["passed"] == 2
    assert res.summary["failed"] == 0


# ---------------------------------------------------------------------------
# Spec: "failed: rows where result.passed is false or output is null"
# Context: Summary rules.  With no evaluation, a dead API row is still failed.
# ---------------------------------------------------------------------------
def test_no_evaluation_counts_dead_rows_as_failed(run_task):
    script = {"a": ["ok"], "b": [500, 500, 500]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "a"}, {"question": "b"}], check=0)
    assert res.summary["passed"] == 1
    assert res.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Spec: "total_prompt_tokens" / "total_completion_tokens"
# Context: Summary rules.  Summed across rows.
# ---------------------------------------------------------------------------
def test_token_totals_sum_across_rows(run_task):
    responder = fake_api.always("#### 5", prompt_tokens=45,
                                completion_tokens=120)
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api, rows=[{"question": "a", "answer": "5"},
                                  {"question": "b", "answer": "5"}], check=0)
    assert res.summary["total_prompt_tokens"] == 90
    assert res.summary["total_completion_tokens"] == 240


# ---------------------------------------------------------------------------
# Spec: "total_api_calls: all HTTP requests, including retries and rejection
#        attempts"
# Context: Summary rules.  (AMBIGUITIES T22 — discarded rejection attempts
# still contribute their tokens.)
# ---------------------------------------------------------------------------
def test_api_calls_and_tokens_include_rejection_attempts(run_task):
    responder = fake_api.always("#### 1", prompt_tokens=10,
                                completion_tokens=2)
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 3},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=[{"question": "q", "answer": "42"}], check=0)
    assert res.summary["total_api_calls"] == 3
    assert res.summary["total_prompt_tokens"] == 30
    assert res.summary["total_completion_tokens"] == 6


# ---------------------------------------------------------------------------
# Spec: "total_api_calls: all HTTP requests, including retries"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_api_calls_include_retries(run_task):
    with fake_api.FakeAPI(fake_api.fail_times(2, "#### 5")) as api:
        res = run_task(api, check=0)
    assert res.summary["total_api_calls"] == 3
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "elapsed_seconds: wall-clock time from first request to last response,
#        rounded to 1 decimal place"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_elapsed_seconds_is_rounded_to_one_decimal(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.25) as api:
        res = run_task(api, check=0)
    elapsed = res.summary["elapsed_seconds"]
    assert isinstance(elapsed, float)
    assert round(elapsed, 1) == elapsed
    assert 0.2 <= elapsed <= 10.0


# ---------------------------------------------------------------------------
# Spec: "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to 1
#        decimal place"
# Context: Summary rules.  The identity must hold against the reported values.
# ---------------------------------------------------------------------------
def test_throughput_rpm_follows_the_formula(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(8)]
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.1) as api:
        res = run_task(api, rows=rows, check=0)
    s = res.summary
    expected = round(s["total_api_calls"] / s["elapsed_seconds"] * 60, 1)
    assert s["throughput_rpm"] == pytest.approx(expected, rel=0.05)


# ---------------------------------------------------------------------------
# Spec: "total: input row count" (AMBIGUITIES T17)
# Context: Summary rules.  An empty input file is a zero-row success.
# ---------------------------------------------------------------------------
def test_empty_input_produces_zero_row_summary(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, input_raw="", check=0)
        assert api.call_count == 0
    s = res.summary
    assert s["total"] == 0 and s["passed"] == 0 and s["failed"] == 0
    assert s["total_api_calls"] == 0
    assert s["throughput_rpm"] == 0.0
    assert res.rows == []


# ---------------------------------------------------------------------------
# Spec: "The input file is JSONL with one object per line."
# Context: Input (AMBIGUITIES T17).  Blank lines are not rows.
# ---------------------------------------------------------------------------
def test_blank_lines_in_input_are_skipped(run_task):
    raw = '{"question": "a", "answer": "5"}\n\n{"question": "b", "answer": "5"}\n'
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, input_raw=raw, check=0)
    assert res.summary["total"] == 2
    assert len(res.rows) == 2


# ---------------------------------------------------------------------------
# Spec: "throughput_rpm: total_api_calls / elapsed_seconds * 60"
# Context: AMBIGUITIES T24 — a run whose elapsed time rounds to 0.0 still
# reports a real throughput rather than 0.0.
# ---------------------------------------------------------------------------
def test_throughput_is_positive_on_a_very_fast_run(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    assert res.summary["total_api_calls"] == 1
    assert res.summary["throughput_rpm"] > 0

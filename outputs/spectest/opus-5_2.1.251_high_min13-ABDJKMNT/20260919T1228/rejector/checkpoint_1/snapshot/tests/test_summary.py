"""The JSON summary printed to stdout after processing."""

from __future__ import annotations

from conftest import make_config


# Spec: the summary object carries exactly the documented keys.
def test_summary_keys(servers, run_cli):
    server = servers(contents=["#### 8"])
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    assert set(result.summary) == {
        "total",
        "passed",
        "failed",
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_api_calls",
        "elapsed_seconds",
        "throughput_rpm",
    }


# Spec: "total: input row count".
def test_total_is_the_input_row_count(servers, run_cli):
    server = servers(contents=["#### 8"])
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(7)]
    result = run_cli(make_config(server.url), rows)
    assert result.summary["total"] == 7


# Spec: "passed: rows where result.passed is true" and "failed: rows where
# result.passed is false or output is null".
def test_passed_and_failed_counts(servers, run_cli):
    server = servers(contents=["#### 8"])
    rows = [
        {"question": "a", "answer": "8"},
        {"question": "b", "answer": "9"},
        {"question": "c", "answer": "8"},
    ]
    result = run_cli(make_config(server.url), rows)
    assert result.summary["passed"] == 2
    assert result.summary["failed"] == 1


# Spec: "when no evaluation is configured, treat successful API rows as passed".
def test_rows_without_evaluation_count_as_passed(servers, run_cli):
    server = servers(contents=["anything"])
    config = make_config(server.url, evaluation=None)
    rows = [{"question": f"q{i}"} for i in range(4)]
    result = run_cli(config, rows)
    assert result.summary["passed"] == 4
    assert result.summary["failed"] == 0


# Spec: "failed: rows where ... output is null" -- an API-failed row counts as
# failed even with no evaluation configured. (T13)
def test_api_failed_row_counts_as_failed_without_evaluation(servers, run_cli):
    server = servers(fail_calls=set(range(50)))
    config = make_config(server.url, evaluation=None)
    result = run_cli(config, [{"question": "q"}])
    assert result.summary["failed"] == 1
    assert result.summary["passed"] == 0
    assert result.rows[0]["result"]["passed"] is None


# Spec: "total_prompt_tokens" / "total_completion_tokens" aggregate usage.
def test_token_totals_sum_across_rows(servers, run_cli):
    server = servers(contents=["#### 8"], prompt_tokens=45, completion_tokens=120)
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(3)]
    result = run_cli(make_config(server.url), rows)
    assert result.summary["total_prompt_tokens"] == 135
    assert result.summary["total_completion_tokens"] == 360


# Spec: token totals cover every response, including discarded rejection
# attempts. (T17)
def test_token_totals_include_discarded_rejection_attempts(servers, run_cli):
    server = servers(contents=["#### 1"], prompt_tokens=10, completion_tokens=2, workers=1)
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 4}
    )
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    assert result.summary["total_prompt_tokens"] == 40
    assert result.summary["total_completion_tokens"] == 8


# Spec: "total_api_calls: all HTTP requests, including retries and rejection
# attempts".
def test_total_api_calls_counts_retries_and_rejection_attempts(servers, run_cli):
    # Call 0 fails with 5xx (retried), then three rejection attempts all fail
    # evaluation: 1 failed + 4 successful calls.
    server = servers(contents=["#### 1"], fail_calls={0}, workers=1)
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 3}
    )
    result = run_cli(config, [{"question": "q", "answer": "8"}])
    assert result.summary["total_api_calls"] == 4
    assert result.summary["total_api_calls"] == server.call_count


# Spec: "elapsed_seconds: wall-clock time from first request to last response,
# rounded to 1 decimal place".
def test_elapsed_seconds_is_rounded_to_one_decimal(servers, run_cli):
    server = servers(contents=["#### 8"], service_time=0.5)
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "8"}])
    elapsed = result.summary["elapsed_seconds"]
    assert round(elapsed, 1) == elapsed
    assert elapsed >= 0.5


# Spec: "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to 1
# decimal place".
def test_throughput_matches_the_formula(servers, run_cli):
    server = servers(contents=["#### 8"], service_time=0.2)
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(6)]
    result = run_cli(make_config(server.url), rows)
    summary = result.summary
    expected = round(summary["total_api_calls"] / summary["elapsed_seconds"] * 60, 1)
    assert summary["throughput_rpm"] == expected


# Spec: a summary is printed "after processing finishes" -- an empty input is
# a legal run of zero rows. (T12)
def test_empty_input_summary(server, run_cli):
    result = run_cli(make_config(server.url), [])
    assert result.exit_code == 0
    assert result.summary["total"] == 0
    assert result.summary["total_api_calls"] == 0
    assert result.summary["elapsed_seconds"] == 0.0
    assert result.summary["throughput_rpm"] == 0.0
    assert result.rows == []

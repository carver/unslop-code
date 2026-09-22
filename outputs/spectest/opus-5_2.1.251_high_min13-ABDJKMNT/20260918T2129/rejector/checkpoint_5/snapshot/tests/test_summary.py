"""The JSON summary printed to stdout after processing."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, always, completion, cycle
from conftest import base_config

SUMMARY_KEYS = {
    "total", "passed", "failed",
    "total_prompt_tokens", "total_completion_tokens", "total_api_calls",
    "elapsed_seconds", "throughput_rpm",
}


# Spec: "print one JSON summary object to stdout" with the documented keys
def test_summary_has_the_documented_keys(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
    assert set(result.summary) == SUMMARY_KEYS


# Spec: "total: input row count"
def test_total_is_the_input_row_count(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(7)])
        result = run_cli(config, rows)
    assert result.summary["total"] == 7


# Spec: "passed: rows where result.passed is true" /
# "failed: rows where result.passed is false or output is null"
def test_passed_and_failed_counts_split_rows(write_config, write_input, run_cli):
    def responder(payload, index):
        question = payload["messages"][1]["content"]
        return Reply(completion("#### 5" if question.startswith("good") else "#### 0"))

    with FakeAPIServer(responder) as api:
        config = write_config(base_config(api.url))
        rows = write_input([
            {"question": "good-0", "answer": "5"},
            {"question": "good-1", "answer": "5"},
            {"question": "bad-0", "answer": "5"},
        ])
        result = run_cli(config, rows)

    assert result.summary["passed"] == 2
    assert result.summary["failed"] == 1


# Spec: "when no evaluation is configured, treat successful API rows as passed"
def test_rows_without_evaluation_count_as_passed(write_config, write_input, run_cli):
    config_map = base_config("")
    del config_map["task"]["evaluation"]
    with FakeAPIServer(always("anything")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        rows = write_input([{"question": f"q{i}"} for i in range(4)])
        result = run_cli(config, rows)

    assert result.summary["passed"] == 4
    assert result.summary["failed"] == 0
    assert all(row["result"]["passed"] is None for row in result.rows)


# Spec: "total_prompt_tokens" / "total_completion_tokens" aggregate usage
def test_token_totals_sum_every_call(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5", prompt_tokens=45, completion_tokens=120)) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(3)])
        result = run_cli(config, rows)

    assert result.summary["total_prompt_tokens"] == 135
    assert result.summary["total_completion_tokens"] == 360


# Spec: "total_api_calls: all HTTP requests, including retries and rejection
# attempts"
def test_total_api_calls_includes_rejection_attempts(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3, "max_tokens": 64}
    with FakeAPIServer(cycle(["#### 1", "#### 2", "#### 5"])) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)

    assert result.summary["total_api_calls"] == call_count == 3


# Spec: "elapsed_seconds: wall-clock time from first request to last
# response, rounded to 1 decimal place"
def test_elapsed_seconds_is_rounded_to_one_decimal(write_config, write_input, run_cli):
    def slow(payload, index):
        return Reply(completion("#### 5"), delay=0.3)

    with FakeAPIServer(slow) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    elapsed = result.summary["elapsed_seconds"]
    assert round(elapsed, 1) == elapsed
    assert elapsed >= 0.3


# Spec: "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to
# 1 decimal place"
def test_throughput_matches_calls_over_elapsed(write_config, write_input, run_cli):
    def slow(payload, index):
        return Reply(completion("#### 5"), delay=0.5)

    # A run long enough that rounding `elapsed_seconds` to one decimal place
    # stays well inside the tolerance below.
    with FakeAPIServer(slow, capacity=4) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(8)])
        result = run_cli(config, rows)

    summary = result.summary
    expected = summary["total_api_calls"] / summary["elapsed_seconds"] * 60
    assert abs(summary["throughput_rpm"] - expected) < max(1.0, expected * 0.1)
    assert round(summary["throughput_rpm"], 1) == summary["throughput_rpm"]


# Spec: summary counts are integers, timings are numbers
def test_summary_value_types(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    summary = result.summary
    for key in ("total", "passed", "failed", "total_prompt_tokens", "total_completion_tokens", "total_api_calls"):
        assert isinstance(summary[key], int)
    assert isinstance(summary["elapsed_seconds"], float)
    assert isinstance(summary["throughput_rpm"], float)

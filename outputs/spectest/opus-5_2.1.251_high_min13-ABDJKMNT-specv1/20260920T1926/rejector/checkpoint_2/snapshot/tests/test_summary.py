"""The stdout summary object."""

from __future__ import annotations

from conftest import base_task
from fake_api import FakeAPI, Reply, always, by_question


# Spec: "After processing finishes, print one JSON summary object to stdout"
# with keys total, passed, failed, total_prompt_tokens,
# total_completion_tokens, total_api_calls, elapsed_seconds, throughput_rpm.
# Context: Output.
def test_summary_keys(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
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


# Spec: "total: input row count"
# Context: Summary rules.
def test_total_is_row_count(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(7)])
        result = run_cli(config, data)
    assert result.summary["total"] == 7


# Spec: "passed: rows where result.passed is true" and "failed: rows where
# result.passed is false or output is null".
# Context: Summary rules.
def test_passed_and_failed_counts(write_config, write_input, run_cli):
    mapping = {
        "a": Reply(content="#### 5"),
        "b": Reply(content="#### 5"),
        "c": Reply(content="#### 9"),
    }
    with FakeAPI(responder=by_question(mapping)) as api:
        config = write_config(base_task(api.url))
        data = write_input(
            [
                {"question": "a", "answer": "5"},
                {"question": "b", "answer": "5"},
                {"question": "c", "answer": "5"},
            ]
        )
        result = run_cli(config, data)
    assert result.summary["passed"] == 2
    assert result.summary["failed"] == 1


# Spec: "passed: ... when no evaluation is configured, treat successful API
# rows as passed"
# Context: Summary rules.
def test_no_evaluation_counts_successful_rows_as_passed(write_config, write_input, run_cli):
    with FakeAPI(responder=always("anything")) as api:
        task = base_task(api.url)
        task.pop("evaluation")
        config = write_config(task)
        data = write_input([{"question": f"q{i}"} for i in range(4)])
        result = run_cli(config, data)
    assert result.summary["passed"] == 4
    assert result.summary["failed"] == 0


# Spec: "total_prompt_tokens" / "total_completion_tokens"
# Context: Summary; summed across every API call including rejection attempts.
def test_token_totals_sum_every_call(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1", prompt_tokens=11, completion_tokens=13)) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3}
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert result.summary["total_prompt_tokens"] == 33
    assert result.summary["total_completion_tokens"] == 39


# Spec: "total_api_calls: all HTTP requests, including retries and rejection
# attempts"
# Context: Summary rules.
def test_total_api_calls_matches_server_count(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 4}
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(3)])
        result = run_cli(config, data)
        server_calls = api.call_count
    assert result.summary["total_api_calls"] == server_calls == 12


# Spec: "elapsed_seconds: wall-clock time from first request to last response,
# rounded to 1 decimal place"
# Context: Summary rules.
def test_elapsed_seconds_rounded_to_one_decimal(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=1, delay=0.3) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(2)])
        result = run_cli(config, data)
    elapsed = result.summary["elapsed_seconds"]
    assert round(elapsed, 1) == elapsed
    assert 0.3 <= elapsed < 10.0


# Spec: "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to 1
# decimal place"
# Context: Summary rules.
def test_throughput_matches_calls_over_elapsed(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=4, delay=0.1) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(8)])
        result = run_cli(config, data)
    summary = result.summary
    expected = summary["total_api_calls"] / summary["elapsed_seconds"] * 60
    assert abs(summary["throughput_rpm"] - expected) < expected * 0.2
    assert round(summary["throughput_rpm"], 1) == summary["throughput_rpm"]


# Spec: "failed: rows where result.passed is false or output is null"
# Context: Summary rules; a null output from exhausted rejection counts once.
def test_failed_counts_null_output_rows_once(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 2}
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(3)])
        result = run_cli(config, data)
    assert result.summary["failed"] == 3
    assert result.summary["passed"] == 0
    assert result.summary["total"] == 3

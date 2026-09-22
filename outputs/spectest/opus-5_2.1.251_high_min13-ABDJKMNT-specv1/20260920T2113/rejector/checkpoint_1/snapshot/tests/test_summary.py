"""The JSON summary printed to stdout after processing."""

from __future__ import annotations

from tests.conftest import task_config
from tests.fake_api import error, ok

SUMMARY_KEYS = {
    "total", "passed", "failed", "total_prompt_tokens", "total_completion_tokens",
    "total_api_calls", "elapsed_seconds", "throughput_rpm",
}


def rows_for(count):
    return [{"question": str(value), "answer": "5"} for value in range(count)]


# "After processing finishes, print one JSON summary object to stdout"
def test_summary_is_a_single_json_object(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), rows_for(3))
    assert run.returncode == 0
    assert len(run.stdout.strip().splitlines()) == 1
    assert set(run.summary) == SUMMARY_KEYS


# "total: input row count" / "passed: rows where result.passed is true"
def test_total_and_passed_counts(cli, api):
    def responder(index, body):
        return ok("#### 5") if index % 2 == 0 else ok("#### 4")

    server = api(responder)
    run = cli.run(task_config(api_url=server.url, rpm=60), rows_for(4))
    assert run.returncode == 0
    assert run.summary["total"] == 4
    assert run.summary["passed"] + run.summary["failed"] == 4
    assert run.summary["passed"] == sum(
        1 for row in run.rows if row["result"]["passed"] is True
    )


# "failed: rows where result.passed is false or output is null"
def test_failed_counts_evaluation_and_api_failures(cli, api):
    def responder(index, body):
        question = body["messages"][-1]["content"]
        if question == "0":
            return error(500)       # API failure -> output null
        if question == "1":
            return ok("#### 4")     # evaluation failure
        return ok("#### 5")

    server = api(responder)
    run = cli.run(task_config(api_url=server.url), rows_for(3))
    assert run.returncode == 0
    assert run.summary["failed"] == 2
    assert run.summary["passed"] == 1


# "passed: ... when no evaluation is configured, treat successful API rows as
#  passed"
def test_no_evaluation_counts_successful_rows_as_passed(cli, api):
    def responder(index, body):
        return error(500) if body["messages"][-1]["content"] == "0" else ok("text")

    server = api(responder)
    config = task_config(api_url=server.url)
    config["task"].pop("evaluation")
    run = cli.run(config, rows_for(3))
    assert run.returncode == 0
    assert all(row["result"]["passed"] is None for row in run.rows)
    assert run.summary["passed"] == 2
    assert run.summary["failed"] == 1


# "total_prompt_tokens" / "total_completion_tokens" sum every response
def test_token_totals(cli, api):
    server = api(lambda index, body: ok("#### 5", prompt_tokens=45, completion_tokens=120))
    run = cli.run(task_config(api_url=server.url), rows_for(3))
    assert run.returncode == 0
    assert run.summary["total_prompt_tokens"] == 135
    assert run.summary["total_completion_tokens"] == 360


# "total_api_calls: all HTTP requests, including retries and rejection attempts"
def test_total_api_calls_includes_retries_and_rejection_attempts(cli, api):
    def responder(index, body):
        return error(503) if index == 0 else ok("#### 9")

    server = api(responder)
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 3},
    )
    run = cli.run(config, rows_for(1))
    assert run.returncode == 0
    # attempt 1: 503 then success; attempts 2 and 3: one call each
    assert run.summary["total_api_calls"] == len(server.log.calls) == 4
    assert run.rows[0]["result"]["attempts"] == 3


# "elapsed_seconds: wall-clock time from first request to last response, rounded
#  to 1 decimal place"
def test_elapsed_seconds_is_rounded_wall_clock(cli, api):
    server = api(lambda index, body: ok("#### 5"), delay=0.4)
    run = cli.run(task_config(api_url=server.url), rows_for(1))
    assert run.returncode == 0
    elapsed = run.summary["elapsed_seconds"]
    assert elapsed >= 0.4
    assert round(elapsed, 1) == elapsed


# "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to 1 decimal
#  place"
def test_throughput_matches_calls_over_elapsed(cli, api):
    server = api(lambda index, body: ok("#### 5"), delay=0.1)
    run = cli.run(task_config(api_url=server.url, rpm=600), rows_for(10))
    assert run.returncode == 0
    summary = run.summary
    assert round(summary["throughput_rpm"], 1) == summary["throughput_rpm"]
    expected = summary["total_api_calls"] / summary["elapsed_seconds"] * 60
    assert abs(summary["throughput_rpm"] - expected) < expected * 0.1

"""The multi-task stdout summary and cross-task scheduling."""

from __future__ import annotations

from tests.conftest import JUDGE_MARKER, SPEC_ROWS, multi_config
from tests.fake_api import ok

GSM8K_ROW = SPEC_ROWS["gsm8k"]
REVIEW_ROW = SPEC_ROWS["review"]
TASK_KEYS = {"total", "passed", "failed", "total_api_calls"}


def gsm8k_and_review(api, score: str = "8"):
    """A server answering the `gsm8k`, `review` and judge prompts."""

    def responder(index, body):
        system = body["messages"][0]["content"]
        if JUDGE_MARKER in system:
            return ok(score)
        return ok("#### 5") if "math" in system else ok("The sea is vast.")

    return api(responder)


def greedy_config(server, *names: str) -> dict:
    """The named spec tasks, all greedy so attempt counts are predictable."""
    config = multi_config(*names, defaults={"api_url": server.url, "rpm": 600})
    for task in config["tasks"].values():
        task["generation"] = {"scheme": "greedy"}
    return config


# "The stdout summary now includes a `tasks` object keyed by executed task name"
def test_summary_has_a_tasks_object_keyed_by_task_name(cli, api):
    server = gsm8k_and_review(api)
    run = cli.run_multi(
        greedy_config(server, "gsm8k", "review"),
        {"gsm8k": [GSM8K_ROW] * 2, "review": [REVIEW_ROW] * 3},
    )
    assert run.returncode == 0, run.stderr
    assert sorted(run.summary["tasks"]) == ["gsm8k", "review"]
    assert set(run.summary["tasks"]["gsm8k"]) == TASK_KEYS


# "tasks": {"gsm8k": {"total", "passed", "failed", "total_api_calls"}}
def test_per_task_counts_describe_that_task_only(cli, api):
    server = gsm8k_and_review(api)
    run = cli.run_multi(
        greedy_config(server, "gsm8k", "review"),
        {"gsm8k": [GSM8K_ROW] * 2, "review": [REVIEW_ROW] * 3},
    )
    tasks = run.summary["tasks"]
    assert tasks["gsm8k"] == {"total": 2, "passed": 2, "failed": 0, "total_api_calls": 2}
    assert tasks["review"]["total"] == 3
    assert tasks["review"]["passed"] == 3


# "per-task `total_api_calls` includes judge calls"
def test_per_task_api_calls_include_judge_calls(cli, api):
    server = gsm8k_and_review(api)
    run = cli.run_multi(greedy_config(server, "review"), {"review": [REVIEW_ROW] * 3})
    assert run.summary["tasks"]["review"]["total_api_calls"] == 6


# top-level totals aggregate every task that ran
def test_top_level_totals_aggregate_tasks(cli, api):
    server = gsm8k_and_review(api, score="2")
    run = cli.run_multi(
        greedy_config(server, "gsm8k", "review"),
        {"gsm8k": [GSM8K_ROW] * 2, "review": [REVIEW_ROW] * 3},
    )
    summary = run.summary
    assert summary["total"] == 5
    assert summary["passed"] == 2 and summary["failed"] == 3
    assert summary["total_api_calls"] == 2 + 6
    assert summary["throughput_rpm"] > 0
    assert summary["elapsed_seconds"] >= 0


# "include only tasks that actually ran"
def test_only_executed_tasks_appear(cli, api):
    server = gsm8k_and_review(api)
    run = cli.run_multi(
        greedy_config(server, "gsm8k", "review"),
        {"gsm8k": [GSM8K_ROW]},
        "--task", "gsm8k",
    )
    assert run.returncode == 0, run.stderr
    assert list(run.summary["tasks"]) == ["gsm8k"]
    assert run.summary["total"] == 1


# "requests from different tasks may run concurrently and may be interleaved"
def test_tasks_run_concurrently(cli, api):
    def responder(index, body):
        system = body["messages"][0]["content"]
        return ok("#### 5") if "math" in system else ok("The sea is vast.")

    server = api(responder, delay=0.05)
    config = multi_config("gsm8k", "review", defaults={"api_url": server.url, "rpm": 600})
    for task in config["tasks"].values():
        task["generation"] = {"scheme": "greedy"}
    config["tasks"]["review"]["evaluation"] = {"type": "contains", "answer_field": "criteria"}
    run = cli.run_multi(config, {"gsm8k": [GSM8K_ROW] * 4, "review": [REVIEW_ROW] * 4})
    assert run.returncode == 0, run.stderr
    assert server.log.max_in_flight > 1
    systems = ["math" in call.body["messages"][0]["content"] for call in server.log.calls]
    assert len(set(systems)) == 2

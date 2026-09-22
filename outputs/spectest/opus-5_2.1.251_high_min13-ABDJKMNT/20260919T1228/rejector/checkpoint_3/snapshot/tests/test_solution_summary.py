"""The per-task summary fields added for multi-solution runs."""

from __future__ import annotations

from conftest import make_config

PASSING = {"question": "q_pass", "answer": "42"}
FAILING = {"question": "q_fail", "answer": "42"}
REPLIES = {"q_pass": "#### 42", "q_fail": "#### 0"}


def task_summary(result) -> dict:
    return result.summary["tasks"]["gsm8k_solve"]


# Spec: per-task summary fields gain `total_solutions`.
def test_total_solutions_counts_every_solution(servers, run_cli):
    server = servers(content_if_contains=REPLIES)
    config = make_config(
        server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=3,
    )
    result = run_cli(config, [PASSING, FAILING])
    assert result.exit_code == 0, result.stderr
    assert task_summary(result)["total_solutions"] == 6


# Spec: per-task summary fields gain `avg_solutions_per_input` -- 450
# solutions over 100 inputs reads 4.5. (T49)
def test_avg_solutions_per_input(servers, run_cli):
    server = servers(content_if_contains=REPLIES)
    config = make_config(
        server.url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 3},
        num_solutions=3,
    )
    result = run_cli(config, [PASSING, FAILING])
    summary = task_summary(result)
    assert summary["total_solutions"] == 3
    assert summary["avg_solutions_per_input"] == 1.5


# Spec: per-task summary fields gain `total_api_calls`, which counts every
# attempt the task made.
def test_total_api_calls_counts_every_attempt(servers, run_cli):
    server = servers(content_if_contains=REPLIES)
    config = make_config(
        server.url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 3},
        num_solutions=3,
    )
    result = run_cli(config, [PASSING, FAILING])
    assert task_summary(result)["total_api_calls"] == 6
    assert result.summary["total_api_calls"] == 6


# Spec: the per-task object keeps its Part 2 keys and gains the new ones. (T48)
def test_per_task_keys_gain_the_new_fields(servers, run_cli):
    server = servers(content_if_contains=REPLIES)
    config = make_config(
        server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=2,
    )
    result = run_cli(config, [PASSING])
    assert set(task_summary(result)) == {
        "total",
        "passed",
        "failed",
        "total_api_calls",
        "total_solutions",
        "avg_solutions_per_input",
    }


# Spec: "Per-task summary fields gain" the new keys, which a Part 1 shaped task
# reports too. (T48)
def test_legacy_task_reports_the_new_fields(servers, run_cli):
    server = servers(content_if_contains=REPLIES)
    result = run_cli(make_config(server.url), [PASSING, FAILING])
    summary = task_summary(result)
    assert summary["total_solutions"] == 2
    assert summary["avg_solutions_per_input"] == 1.0


# Spec: `total`, `passed` and `failed` still count input rows, so a row counts
# as passed once it has a passing solution. (T53)
def test_row_counts_follow_the_passing_solutions(servers, run_cli):
    server = servers(content_if_contains=REPLIES)
    config = make_config(
        server.url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 3},
        num_solutions=3,
    )
    result = run_cli(config, [PASSING, FAILING])
    summary = task_summary(result)
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1


# Spec: a task that produced no solutions at all averages zero. (T49)
def test_avg_solutions_is_zero_without_solutions(servers, run_cli):
    server = servers(fail_calls=set(range(20)), fail_status=400)
    config = make_config(
        server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=2,
    )
    result = run_cli(config, [PASSING])
    summary = task_summary(result)
    assert summary["total_solutions"] == 0
    assert summary["avg_solutions_per_input"] == 0.0

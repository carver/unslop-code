"""The `tasks` object in the run summary, and cross-task scheduling."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, completion, system_of, user_of
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config

TASK_KEYS = {
    "total", "passed", "failed", "total_solutions", "avg_solutions_per_input",
    "total_api_calls",
}
BOTH_TASKS = {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK}


def _answers(payload, index):
    """gsm8k answers `5`; mmlu answers `B` unless the question says `bad`."""
    if "math" in system_of(payload):
        return Reply(completion("#### 5" if "bad" not in user_of(payload) else "#### 0"))
    return Reply(completion("The answer is B) Paris" if "bad" not in user_of(payload) else "D"))


def _gsm8k_rows(count, bad=0):
    return [
        {"question": f"{'bad' if i < bad else 'good'} {i}", "answer": "5"} for i in range(count)
    ]


def _mmlu_rows(count, bad=0):
    return [
        {
            "question": f"{'bad' if i < bad else 'good'} {i}",
            "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid",
            "answer": "B",
        }
        for i in range(count)
    ]


def _run(write_config, write_input, run_argv, gsm8k_rows, mmlu_rows, *extra, tasks=None):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, tasks or BOTH_TASKS))
        math = write_input(gsm8k_rows, name="math.jsonl")
        qa = write_input(mmlu_rows, name="qa.jsonl")
        return run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}", *extra
        )


# Spec: "The stdout summary now includes a `tasks` object keyed by executed
# task name"
def test_summary_has_a_tasks_object_keyed_by_task_name(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, _gsm8k_rows(2), _mmlu_rows(1))
    assert sorted(result.summary["tasks"]) == ["gsm8k", "mmlu"]


# Spec: per-task entries carry "total", "passed", "failed", "total_api_calls",
# and Part 3 adds "total_solutions" and "avg_solutions_per_input"
def test_per_task_entries_have_the_documented_keys(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, _gsm8k_rows(2), _mmlu_rows(1))
    assert set(result.summary["tasks"]["gsm8k"]) == TASK_KEYS


# Spec: per-task "total", "passed" and "failed" count that task's rows
def test_per_task_counts_cover_only_that_task(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, _gsm8k_rows(4, bad=1), _mmlu_rows(3, bad=2))
    tasks = result.summary["tasks"]

    counted = {
        name: {key: task[key] for key in ("total", "passed", "failed", "total_api_calls")}
        for name, task in tasks.items()
    }
    assert counted["gsm8k"] == {"total": 4, "passed": 3, "failed": 1, "total_api_calls": 4}
    assert counted["mmlu"] == {"total": 3, "passed": 1, "failed": 2, "total_api_calls": 3}


# Spec: the top-level totals aggregate every task that ran
def test_top_level_totals_aggregate_the_tasks(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, _gsm8k_rows(4, bad=1), _mmlu_rows(3, bad=2))
    summary = result.summary

    assert summary["total"] == 7
    assert summary["passed"] == 4
    assert summary["failed"] == 3
    assert summary["total_api_calls"] == 7


# Spec: "include only tasks that actually ran"
def test_only_executed_tasks_appear(write_config, write_input, run_argv):
    with FakeAPIServer(_answers) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input(_gsm8k_rows(2), name="math.jsonl")
        result = run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--task", "gsm8k"
        )

    assert list(result.summary["tasks"]) == ["gsm8k"]
    assert result.summary["total"] == 2


# Spec: "Existing behavior from Part 1 is unchanged unless stated here" - a
# single-task config still prints the Part 1 summary
def test_single_task_config_summary_is_unchanged(write_config, write_input, run_cli):
    with FakeAPIServer(_answers) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input(_gsm8k_rows(2)))

    assert "tasks" not in result.summary
    assert result.summary["total"] == 2


# Spec: "requests from different tasks may run concurrently and may be
# interleaved"
def test_tasks_run_concurrently(write_config, write_input, run_argv):
    def slow(payload, index):
        return Reply(_answers(payload, index).body, delay=0.2)

    with FakeAPIServer(slow, capacity=16) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input(_gsm8k_rows(8), name="math.jsonl")
        qa = write_input(_mmlu_rows(8), name="qa.jsonl")
        result = run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}"
        )
        peak = api.peak_in_flight
        first_half = ["math" in system_of(payload) for payload in api.payloads[:8]]

    assert result.returncode == 0
    assert peak > 8
    assert set(first_half) == {True, False}


# Spec: "within each task's output file, row order must still match input
# order"
def test_row_order_matches_input_order_per_task(write_config, write_input, run_argv):
    def slow(payload, index):
        return Reply(_answers(payload, index).body, delay=0.05 * (index % 4))

    with FakeAPIServer(slow, capacity=16) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        gsm8k_rows = _gsm8k_rows(6)
        mmlu_rows = _mmlu_rows(6)
        math = write_input(gsm8k_rows, name="math.jsonl")
        qa = write_input(mmlu_rows, name="qa.jsonl")
        result = run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}"
        )

    assert [row["input"] for row in result.task_rows("gsm8k")] == gsm8k_rows
    assert [row["input"] for row in result.task_rows("mmlu")] == mmlu_rows


# Spec: "throughput_rpm" still covers the whole run, judge calls included
def test_throughput_covers_the_whole_run(write_config, write_input, run_argv):
    def slow(payload, index):
        return Reply(_answers(payload, index).body, delay=0.5)

    with FakeAPIServer(slow, capacity=4) as api:
        config = write_config(multi_config(api.url, BOTH_TASKS))
        math = write_input(_gsm8k_rows(4), name="math.jsonl")
        qa = write_input(_mmlu_rows(4), name="qa.jsonl")
        result = run_argv(
            "--config", config, "--input", f"gsm8k={math}", "--input", f"mmlu={qa}"
        )

    summary = result.summary
    expected = summary["total_api_calls"] / summary["elapsed_seconds"] * 60

    assert abs(summary["throughput_rpm"] - expected) < max(1.0, expected * 0.1)

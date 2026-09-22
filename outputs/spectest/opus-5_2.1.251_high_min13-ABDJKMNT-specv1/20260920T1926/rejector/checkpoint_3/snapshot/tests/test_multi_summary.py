"""The `tasks` object in the stdout summary, and cross-task scheduling."""

from __future__ import annotations

from conftest import base_defaults, choice_task, judge_task, math_task, task_rows
from fake_api import FakeAPI, Reply, always, by_question, by_system

MATH_ROW = {"question": "2 + 3?", "answer": "5"}
CHOICE_ROW = {"question": "capital?", "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B"}


def two_task_document(api_url: str) -> dict:
    return {
        "defaults": base_defaults(api_url),
        "tasks": {"gsm8k": math_task(), "mmlu": choice_task()},
    }


def run_multi(write_yaml, run_args, workdir, data, config, *extra):
    return run_args(
        "run", "--config", str(config), "--input-dir", str(data),
        "--output", str(workdir / "results"), *extra,
    )


# Spec: "The stdout summary now includes a `tasks` object keyed by executed
# task name" with per-task "total", "passed", "failed", "total_api_calls",
# which Part 3 gains "total_solutions" and "avg_solutions_per_input" beside.
# Context: Summary And Scheduling / Output Changes.
def test_summary_has_a_tasks_object(write_yaml, write_inputs, run_args, workdir):
    responder = by_question(
        {"2 + 3?": Reply(content="#### 5"), "capital?\n\nA) London\nB) Paris\nC) Berlin\nD) Madrid": Reply(content="B")}
    )
    with FakeAPI(responder=responder) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW, MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_multi(write_yaml, run_args, workdir, data, config)
    summary = result.summary
    assert summary["tasks"]["gsm8k"] == {
        "total": 2, "passed": 2, "failed": 0, "total_api_calls": 2,
        "total_solutions": 2, "avg_solutions_per_input": 1.0,
    }
    assert summary["tasks"]["mmlu"] == {
        "total": 1, "passed": 1, "failed": 0, "total_api_calls": 1,
        "total_solutions": 1, "avg_solutions_per_input": 1.0,
    }


# Spec: top-level keys of the summary are unchanged and aggregate every task.
# Context: Summary And Scheduling example.
def test_top_level_totals_aggregate_all_tasks(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW, MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_multi(write_yaml, run_args, workdir, data, config)
    summary = result.summary
    assert summary["total"] == 3
    assert summary["passed"] + summary["failed"] == 3
    assert summary["total_api_calls"] == 3
    assert summary["elapsed_seconds"] > 0
    assert summary["throughput_rpm"] > 0


# Spec: "include only tasks that actually ran"
# Context: Summary And Scheduling / Rules.
def test_only_executed_tasks_appear(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW], "mmlu": [CHOICE_ROW]})
        result = run_multi(write_yaml, run_args, workdir, data, config, "--task", "gsm8k")
    assert list(result.summary["tasks"]) == ["gsm8k"]


# Spec: "per-task `total_api_calls` includes judge calls"
# Context: Summary And Scheduling / Rules.
def test_per_task_api_calls_include_judge_calls(write_yaml, write_inputs, run_args, workdir):
    document = {
        "defaults": base_defaults("placeholder"),
        "tasks": {"gsm8k": math_task(), "review": judge_task()},
    }
    responder = by_system(
        {
            "Solve the math problem.": Reply(content="#### 5"),
            "You are a writing assistant.": Reply(content="a poem"),
            "You are a quality evaluator.": Reply(content="8"),
        }
    )
    with FakeAPI(responder=responder) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs(
            {"gsm8k": [MATH_ROW], "review": [{"prompt_text": "p", "criteria": "clarity"}] * 2}
        )
        result = run_multi(write_yaml, run_args, workdir, data, config)
    tasks = result.summary["tasks"]
    assert tasks["gsm8k"]["total_api_calls"] == 1
    assert tasks["review"]["total_api_calls"] == 4
    assert result.summary["total_api_calls"] == 5


# Spec: "requests from different tasks may run concurrently and may be
# interleaved"
# Context: Summary And Scheduling / Rules.
def test_tasks_run_concurrently(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5 B"), slots=8, delay=0.1) as api:
        config = write_yaml(two_task_document(api.url))
        data = write_inputs({"gsm8k": [MATH_ROW] * 4, "mmlu": [CHOICE_ROW] * 4})
        result = run_multi(write_yaml, run_args, workdir, data, config)
        assert api.max_concurrent > 4
    assert result.summary["total"] == 8


# Spec: "within each task's output file, row order must still match input
# order"
# Context: Summary And Scheduling / Rules.
def test_row_order_matches_input_order_per_task(write_yaml, write_inputs, run_args, workdir):
    math_rows = [{"question": f"q{index}", "answer": str(index)} for index in range(6)]
    responder = by_question(
        {f"q{index}": Reply(content=f"#### {index}") for index in range(6)}
    )
    with FakeAPI(responder=responder, delay=0.02) as api:
        document = {"defaults": base_defaults(api.url), "tasks": {"gsm8k": math_task()}}
        config = write_yaml(document)
        data = write_inputs({"gsm8k": math_rows})
        result = run_multi(write_yaml, run_args, workdir, data, config)
    written = task_rows(result, "gsm8k")
    assert [row["input"]["question"] for row in written] == [f"q{index}" for index in range(6)]
    assert all(row["result"]["passed"] for row in written)


# Spec: "passed"/"failed" counting is unchanged per task.
# Context: Summary And Scheduling; a failing row is counted in its own task.
def test_failures_are_counted_per_task(write_yaml, write_inputs, run_args, workdir):
    responder = by_question(
        {
            "q0": Reply(content="#### 0"),
            "q1": Reply(content="#### 99"),
        }
    )
    with FakeAPI(responder=responder) as api:
        document = {"defaults": base_defaults(api.url), "tasks": {"gsm8k": math_task()}}
        config = write_yaml(document)
        data = write_inputs(
            {"gsm8k": [{"question": "q0", "answer": "0"}, {"question": "q1", "answer": "1"}]}
        )
        result = run_multi(write_yaml, run_args, workdir, data, config)
    assert result.summary["tasks"]["gsm8k"] == {
        "total": 2, "passed": 1, "failed": 1, "total_api_calls": 2,
        "total_solutions": 2, "avg_solutions_per_input": 1.0,
    }

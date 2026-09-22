"""Spec section: Part 2 / Summary And Scheduling."""
from __future__ import annotations

import copy
import json

import pytest

from conftest import (GSM8K_TASK, JUDGE_TASK, MMLU_TASK, base_config,
                      judge_responder, multi_config)
from mock_server import MockAPI, always, completion


MATH_ROW = {"question": "5+3?", "answer": "8"}
QA_ROW = {"question": "capital?", "a": "London", "b": "Paris", "c": "Berlin",
          "d": "Madrid", "answer": "B"}


def _responder(req, i):
    user = req["messages"][-1]["content"]
    if "capital" in user:
        return 200, completion("The answer is B) Paris")
    return 200, completion("#### 8")


def _two_task_cfg(api_url):
    return multi_config(api_url, {
        "gsm8k": copy.deepcopy(GSM8K_TASK),
        "mmlu": copy.deepcopy(MMLU_TASK),
    })


# ---------------------------------------------------------------------------
# Phrase: "The stdout summary now includes a `tasks` object keyed by executed
#          task name"
# Context: Part 2 / Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_summary_has_a_tasks_object_keyed_by_task_name(run_tool, write_config,
                                                       write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    assert set(res.summary["tasks"]) == {"gsm8k", "mmlu"}


# ---------------------------------------------------------------------------
# Phrase: the summary JSON block's per-task shape
#         {"total": .., "passed": .., "failed": .., "total_api_calls": ..}
# Context: Part 2 / Summary And Scheduling (AMBIGUITIES T34).
# ---------------------------------------------------------------------------
def test_per_task_summary_keys(run_tool, write_config, write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW, MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    entry = res.summary["tasks"]["gsm8k"]
    assert set(entry) == {"total", "passed", "failed", "total_api_calls"}
    assert entry["total"] == 2
    assert entry["passed"] == 2
    assert entry["failed"] == 0
    assert entry["total_api_calls"] == 2


# Context: same block - per-task pass/fail counts are independent.
def test_per_task_counts_are_independent(run_tool, write_config, write_input,
                                         workdir):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        if "capital" in user:
            return 200, completion("The answer is C) Berlin")   # wrong
        return 200, completion("#### 8")                        # right

    with MockAPI(responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW, MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    tasks = res.summary["tasks"]
    assert (tasks["gsm8k"]["passed"], tasks["gsm8k"]["failed"]) == (2, 0)
    assert (tasks["mmlu"]["passed"], tasks["mmlu"]["failed"]) == (0, 1)


# ---------------------------------------------------------------------------
# Phrase: "include only tasks that actually ran"
# Context: Part 2 / Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_summary_omits_unselected_tasks(run_tool, write_config, write_input,
                                        workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}"], output=out,
                       extra=["--task", "gsm8k"])
    assert res.returncode == 0, res
    assert list(res.summary["tasks"]) == ["gsm8k"]


# ---------------------------------------------------------------------------
# Phrase: the top-level summary keys
#         total / passed / failed / total_api_calls / elapsed_seconds /
#         throughput_rpm
# Context: Part 2 / Summary And Scheduling.  Top-level values are the sums
# across executed tasks.
# ---------------------------------------------------------------------------
def test_top_level_totals_sum_across_tasks(run_tool, write_config,
                                           write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW] * 3, name="math.jsonl")
        qa = write_input([QA_ROW] * 2, name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    s = res.summary
    assert s["total"] == 5
    assert s["passed"] == 5
    assert s["failed"] == 0
    assert s["total_api_calls"] == 5
    assert s["total"] == s["tasks"]["gsm8k"]["total"] + s["tasks"]["mmlu"]["total"]
    assert (s["total_api_calls"]
            == sum(t["total_api_calls"] for t in s["tasks"].values()))


def test_top_level_summary_still_has_part1_keys(run_tool, write_config,
                                                write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW], name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    s = res.summary
    for key in ("total", "passed", "failed", "total_api_calls",
                "elapsed_seconds", "throughput_rpm"):
        assert key in s, key
    assert isinstance(s["elapsed_seconds"], float)
    assert isinstance(s["throughput_rpm"], float)


# Context: same block - Part 1's token totals are kept and aggregated
# (AMBIGUITIES T33).
def test_top_level_token_totals_are_aggregated(run_tool, write_config,
                                               write_input, workdir):
    with MockAPI(_responder) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW] * 2, name="math.jsonl")
        qa = write_input([QA_ROW], name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    assert res.summary["total_prompt_tokens"] == 45 * 3
    assert res.summary["total_completion_tokens"] == 120 * 3


# ---------------------------------------------------------------------------
# Phrase: "per-task `total_api_calls` includes judge calls"
# Context: Part 2 / Summary And Scheduling.
# ---------------------------------------------------------------------------
def test_per_task_api_calls_include_judge_calls(run_tool, write_config,
                                                write_input, workdir):
    def responder(req, i):
        system = req["messages"][0]["content"]
        if "evaluator" in system.lower():
            return 200, completion("9")
        user = req["messages"][-1]["content"]
        if "5+3" in user:
            return 200, completion("#### 8")
        return 200, completion("a response")

    with MockAPI(responder) as api:
        cfg = write_config(multi_config(api.url, {
            "gsm8k": copy.deepcopy(GSM8K_TASK),
            "review": copy.deepcopy(JUDGE_TASK),
        }))
        math = write_input([MATH_ROW] * 2, name="math.jsonl")
        rev = write_input([{"prompt_text": "p1", "criteria": "c"},
                           {"prompt_text": "p2", "criteria": "c"}],
                          name="rev.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"review={rev}"], output=out)
    assert res.returncode == 0, res
    s = res.summary
    assert s["tasks"]["gsm8k"]["total_api_calls"] == 2
    assert s["tasks"]["review"]["total_api_calls"] == 4
    assert s["total_api_calls"] == 6


# ---------------------------------------------------------------------------
# Phrase: "judge calls count toward throughput"
# Context: Part 2 / Summary And Scheduling.  throughput_rpm is derived from
# the call total, judge calls included.
# ---------------------------------------------------------------------------
def test_throughput_counts_judge_calls(run_tool, write_config, write_input,
                                       workdir):
    with MockAPI(judge_responder(), delay=0.3) as api:
        cfg = write_config(multi_config(api.url,
                                        {"review": copy.deepcopy(JUDGE_TASK)}))
        rows = [{"prompt_text": f"p{i}", "criteria": "c"} for i in range(5)]
        data = write_input(rows)
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review={data}"], output=out)
    assert res.returncode == 0, res
    s = res.summary
    assert s["total_api_calls"] == 10
    # `elapsed_seconds` is rounded to 1dp, so bound the throughput by the
    # interval the unrounded elapsed time could have come from.
    elapsed = s["elapsed_seconds"]
    low = s["total_api_calls"] / (elapsed + 0.05) * 60
    high = s["total_api_calls"] / max(elapsed - 0.05, 1e-9) * 60
    assert low <= s["throughput_rpm"] <= high


# ---------------------------------------------------------------------------
# Phrase: "for single-task configs, the stdout summary keeps its previous keys
#          and has no `tasks` object"
# Context: Part 2 / CLI Changes.
# ---------------------------------------------------------------------------
def test_single_task_summary_has_no_tasks_object(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([MATH_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert "tasks" not in res.summary


def test_single_task_summary_keeps_part1_keys(run_tool, write_config,
                                              write_input):
    with MockAPI(always("#### 8")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([MATH_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert set(res.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm"}


# ---------------------------------------------------------------------------
# Phrase: "requests from different tasks may run concurrently and may be
#          interleaved"
# Context: Part 2 / Summary And Scheduling.  With a slow server, two tasks'
# requests must overlap rather than run one task after the other.
# ---------------------------------------------------------------------------
def test_tasks_run_concurrently(run_tool, write_config, write_input, workdir):
    with MockAPI(_responder, delay=0.25) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW] * 4, name="math.jsonl")
        qa = write_input([QA_ROW] * 4, name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
        max_inflight = api.max_inflight
    assert res.returncode == 0, res
    assert max_inflight > 4, (
        f"tasks did not overlap: max in-flight was {max_inflight}")


# Context: same phrase - elapsed_seconds spans the whole run, not one task.
def test_elapsed_seconds_spans_the_whole_run(run_tool, write_config,
                                             write_input, workdir):
    with MockAPI(_responder, delay=0.2) as api:
        cfg = write_config(_two_task_cfg(api.url))
        math = write_input([MATH_ROW] * 2, name="math.jsonl")
        qa = write_input([QA_ROW] * 2, name="qa.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={math}", f"mmlu={qa}"], output=out)
    assert res.returncode == 0, res
    assert res.summary["elapsed_seconds"] >= 0.2


# ---------------------------------------------------------------------------
# Phrase: "within each task's output file, row order must still match input
#          order"
# Context: Part 2 / Summary And Scheduling.  Responses arrive out of order but
# rows are written by input index.
# ---------------------------------------------------------------------------
def test_row_order_matches_input_order_per_task(run_tool, write_config,
                                                write_input, workdir):
    import time

    def responder(req, i):
        user = req["messages"][-1]["content"]
        # Earlier rows answer more slowly, so completions arrive reversed.
        index = int(user.split("#")[-1])
        time.sleep(0.25 - 0.02 * index)
        return 200, completion(f"#### {index}")

    task = copy.deepcopy(GSM8K_TASK)
    task["prompt"]["user"] = "{question}"
    with MockAPI(responder) as api:
        cfg = write_config(multi_config(api.url, {"gsm8k": task}))
        rows = [{"question": f"item #{i}", "answer": str(i)} for i in range(6)]
        data = write_input(rows)
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
    assert res.returncode == 0, res
    written = res.rows_for("gsm8k")
    assert [r["input"]["question"] for r in written] == \
        [f"item #{i}" for i in range(6)]
    assert all(r["result"]["passed"] for r in written)

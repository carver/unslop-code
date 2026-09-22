"""Spec section: Part 3 / Output Changes (per-task summary fields)."""
from __future__ import annotations

import copy

from conftest import COT_SETUP, GSM8K_TASK, base_config, icl_config, multi_config
from mock_server import MockAPI, always, completion


ROW = {"question": "What is 15 + 27?", "answer": "42"}


def _sample_task(num_solutions):
    task = copy.deepcopy(GSM8K_TASK)
    task["generation"] = {"scheme": "sample", "temperature": 0.7}
    task["num_solutions"] = num_solutions
    return task


# ---------------------------------------------------------------------------
# Phrase: the per-task summary block gains "total_solutions",
#         "avg_solutions_per_input" and "total_api_calls"
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_per_task_summary_gains_solution_fields(run_tool, write_config,
                                                write_input, workdir):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(multi_config(api.url, {"gsm8k": _sample_task(3)}))
        data = write_input([ROW, ROW], name="g.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
    assert res.returncode == 0, res
    entry = res.summary["tasks"]["gsm8k"]
    assert entry["total"] == 2
    assert entry["total_solutions"] == 6
    assert entry["avg_solutions_per_input"] == 3.0
    assert entry["total_api_calls"] == 6


# Context: same block - `avg_solutions_per_input` is total_solutions / total
# and need not be a whole number (the spec's 450 / 100 = 4.5).
def test_avg_solutions_per_input_is_fractional(run_tool, write_config,
                                               write_input, workdir):
    seen = {}

    def responder(req, i):
        user = req["messages"][-1]["content"]
        index = seen.get(user, 0)
        seen[user] = index + 1
        if user == "q good":
            return 200, completion("#### 42")          # 2 passes
        return 200, completion("#### 42" if index == 0 else "#### 0")

    task = copy.deepcopy(GSM8K_TASK)
    task["generation"] = {"scheme": "rejection", "temperature": 0.7,
                          "max_attempts": 2}
    task["num_solutions"] = 2
    with MockAPI(responder) as api:
        cfg = write_config(multi_config(api.url, {"gsm8k": task}))
        data = write_input([{"question": "q good", "answer": "42"},
                            {"question": "q half", "answer": "42"}],
                           name="g.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
    assert res.returncode == 0, res
    entry = res.summary["tasks"]["gsm8k"]
    assert entry["total"] == 2
    assert entry["total_solutions"] == 3
    assert entry["avg_solutions_per_input"] == 1.5


# Context: same block - rejection rows that collect fewer solutions than
# requested lower the average.
def test_total_solutions_counts_emitted_outputs(run_tool, write_config,
                                                write_input, workdir):
    def responder(req, i):
        return 200, completion("#### 42" if i % 2 == 0 else "#### 0")

    task = copy.deepcopy(GSM8K_TASK)
    task["generation"] = {"scheme": "rejection", "temperature": 0.7,
                          "max_attempts": 3}
    task["num_solutions"] = 3
    with MockAPI(responder) as api:
        cfg = write_config(multi_config(api.url, {"gsm8k": task}))
        data = write_input([ROW], name="g.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
    assert res.returncode == 0, res
    entry = res.summary["tasks"]["gsm8k"]
    assert entry["total_solutions"] == len(res.rows_for("gsm8k")[0]["output"])
    assert entry["avg_solutions_per_input"] == float(entry["total_solutions"])


# ---------------------------------------------------------------------------
# Phrase: "Per-task summary fields gain" (AMBIGUITIES T50) - the Part 2 keys
#         stay, and the new fields are added for multi-solution / ICL tasks.
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_per_task_summary_keeps_part2_keys(run_tool, write_config,
                                           write_input, workdir):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(multi_config(api.url, {"gsm8k": _sample_task(2)}))
        data = write_input([ROW], name="g.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
    assert res.returncode == 0, res
    entry = res.summary["tasks"]["gsm8k"]
    assert set(entry) == {"total", "passed", "failed", "total_api_calls",
                          "total_solutions", "avg_solutions_per_input"}


# Context: same phrase (AMBIGUITIES T50) - a single-task Part 3 run reports the
# new fields on the top-level summary object.
def test_single_task_summary_reports_solution_fields(run_tool, write_config,
                                                     write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], num_solutions=2,
                                      generation={"scheme": "sample",
                                                  "temperature": 0.7}))
        data = write_input([ROW, ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.summary["total_solutions"] == 4
    assert res.summary["avg_solutions_per_input"] == 2.0
    assert res.summary["total_api_calls"] == 4


# Context: same phrase (AMBIGUITIES T50) - a legacy single-task run keeps the
# Part 1 summary key set exactly.
def test_legacy_summary_key_set_is_unchanged(run_tool, write_config,
                                             write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert set(res.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm"}


# ---------------------------------------------------------------------------
# Phrase: "`total_api_calls`" - every attempt's request is counted, including
#         attempts that failed evaluation.
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_total_api_calls_counts_every_attempt(run_tool, write_config,
                                              write_input, workdir):
    task = copy.deepcopy(GSM8K_TASK)
    task["generation"] = {"scheme": "rejection", "temperature": 0.7,
                          "max_attempts": 4}
    task["num_solutions"] = 2
    with MockAPI(always("#### 0")) as api:
        cfg = write_config(multi_config(api.url, {"gsm8k": task}))
        data = write_input([ROW], name="g.jsonl")
        out = str(workdir / "results")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
    assert res.returncode == 0, res
    assert res.summary["tasks"]["gsm8k"]["total_api_calls"] == 4
    assert res.summary["tasks"]["gsm8k"]["total_solutions"] == 0
    assert res.summary["tasks"]["gsm8k"]["avg_solutions_per_input"] == 0.0


# ---------------------------------------------------------------------------
# Phrase: "`result.passed` is the count of passing solutions" - the summary's
#         row-level `passed`/`failed` (AMBIGUITIES T49) still count rows: a row
#         with at least one solution counts as passed.
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_summary_row_counts_with_list_rows(run_tool, write_config,
                                           write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        return 200, completion("#### 42" if user.endswith("good") else "#### 0")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=2,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 2}))
        data = write_input([{"question": "q good", "answer": "42"},
                            {"question": "q bad", "answer": "42"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.summary["total"] == 2
    assert res.summary["passed"] == 1
    assert res.summary["failed"] == 1

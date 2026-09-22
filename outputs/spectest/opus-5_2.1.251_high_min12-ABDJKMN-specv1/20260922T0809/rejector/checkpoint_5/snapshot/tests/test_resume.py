"""Spec section: Resume (`--resume`)."""
from __future__ import annotations

import copy
import json

import pytest

from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config, rows_of
from mock_server import MockAPI, always

SOLVED = "#### 5"


def done_row(index, *, output=SOLVED, passed=True, field="solution"):
    """A completed single-solution result row as the tool would write it."""
    return {
        "input": {"question": f"q{index}", "answer": "5"},
        "output": None if output is None else {field: output},
        "result": {"passed": passed, "extracted_answer": "5", "attempts": 1},
        "meta": {"model": "gpt-4", "prompt_tokens": 45,
                 "completion_tokens": 120, "total_tokens": 165,
                 "latency_ms": 10, "finish_reason": "stop"},
    }


def list_row(index, solutions, *, field="solution"):
    """A completed Part 3 list-format row with `solutions` entries."""
    return {
        "input": {"question": f"q{index}", "answer": "5"},
        "output": [{field: SOLVED, "icl_setup": None}
                   for _ in range(solutions)],
        "result": {"passed": solutions, "failed": 0, "attempts": solutions},
        "meta": [],
    }


def write_existing(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def prompts_of(api):
    return [req["messages"][-1]["content"] for req in api.requests]


# ---------------------------------------------------------------------------
# Phrase: "if `--resume` is set and the output file already exists, inspect the
#          existing output to determine how many input rows are already
#          complete" / "the existing line count gives the number of leading
#          rows to skip" / "append new rows to the existing output file"
# Context: Resume.
# ---------------------------------------------------------------------------
def test_resume_skips_completed_rows_and_appends(run_tool, write_config,
                                                 write_input, workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [done_row(i) for i in range(4)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, output=out, extra=["--resume"])
        sent = prompts_of(api)
    assert res.returncode == 0, res
    # rows overlap, so compare the multiset of prompts, not their order
    assert sorted(sent) == [f"q{i}" for i in range(4, 10)], sent
    rows = res.rows
    assert len(rows) == 10
    assert [r["input"]["question"] for r in rows] == [f"q{i}"
                                                      for i in range(10)]


# ---------------------------------------------------------------------------
# Phrase: "the summary covers only newly processed rows and includes
#          `resumed_from`"
# Context: Resume - the example summary has total 50 / resumed_from 50.
# ---------------------------------------------------------------------------
def test_resume_summary_counts_only_new_rows(run_tool, write_config,
                                             write_input, workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [done_row(i) for i in range(4)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, output=out, extra=["--resume"])
    assert res.returncode == 0, res
    summary = res.summary
    assert summary["resumed_from"] == 4
    assert summary["total"] == 6
    assert summary["passed"] == 6
    assert summary["total_api_calls"] == 6


# ---------------------------------------------------------------------------
# Phrase: "if `--resume` is set and the output file already exists"
# Context: Resume.  With no output file yet, everything is processed and
# `resumed_from` is 0.
# ---------------------------------------------------------------------------
def test_resume_without_existing_output(run_tool, write_config, write_input):
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(3))
        res = run_tool(cfg, data, extra=["--resume"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    assert res.summary["resumed_from"] == 0
    assert res.summary["total"] == 3
    assert len(res.rows) == 3


# Context: Resume - an already complete output file leaves nothing to do.
def test_resume_with_everything_done(run_tool, write_config, write_input,
                                     workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [done_row(i) for i in range(3)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(3))
        res = run_tool(cfg, data, output=out, extra=["--resume"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 0
    assert res.summary["resumed_from"] == 3
    assert res.summary["total"] == 0
    assert len(res.rows) == 3


# Context: Resume - without the flag the output file is rewritten from row 0.
def test_without_resume_output_is_overwritten(run_tool, write_config,
                                              write_input, workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [done_row(i) for i in range(4)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(6))
        res = run_tool(cfg, data, output=out)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 6
    assert len(res.rows) == 6
    assert "resumed_from" not in res.summary


# ---------------------------------------------------------------------------
# Phrase: "when a prior output row represents an incomplete multi-solution or
#          rejection result with fewer passing solutions than `num_solutions`,
#          do not skip that row; reprocess it from scratch"
# Context: Resume.  A rejection row that never found a passing sample.
# ---------------------------------------------------------------------------
def test_resume_reprocesses_incomplete_rejection_row(run_tool, write_config,
                                                     write_input, workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [done_row(0), done_row(1),
                         done_row(2, output=None, passed=False)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 2}))
        data = write_input(rows_of(5))
        res = run_tool(cfg, data, output=out, extra=["--resume"])
        sent = prompts_of(api)
    assert res.returncode == 0, res
    assert sorted(sent) == ["q2", "q3", "q4"], sent
    assert res.summary["resumed_from"] == 2
    assert res.summary["total"] == 3
    rows = res.rows
    assert len(rows) == 5
    assert rows[2]["output"] == {"solution": SOLVED}


# Context: Resume - a multi-solution row holding fewer solutions than
# `num_solutions` is reprocessed from scratch.
def test_resume_reprocesses_incomplete_multi_solution_row(run_tool,
                                                          write_config,
                                                          write_input,
                                                          workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [list_row(0, 3), list_row(1, 1)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=3,
            generation={"scheme": "sample", "temperature": 0.8}))
        data = write_input(rows_of(4))
        res = run_tool(cfg, data, output=out, extra=["--resume"])
        sent = prompts_of(api)
    assert res.returncode == 0, res
    assert sorted(sent) == ["q1", "q1", "q1", "q2", "q2", "q2",
                            "q3", "q3", "q3"], sent
    assert res.summary["resumed_from"] == 1
    rows = res.rows
    assert len(rows) == 4
    assert len(rows[1]["output"]) == 3


# Context: Resume - a greedy row that simply failed its evaluation is complete;
# only multi-solution and rejection rows are reprocessed.
def test_resume_keeps_failed_greedy_row(run_tool, write_config, write_input,
                                        workdir):
    out = str(workdir / "results.jsonl")
    write_existing(out, [done_row(0), done_row(1, output="#### 9",
                                               passed=False)])
    with MockAPI(always(SOLVED)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(3))
        res = run_tool(cfg, data, output=out, extra=["--resume"])
        sent = prompts_of(api)
    assert res.returncode == 0, res
    assert sorted(sent) == ["q2"], sent
    assert res.summary["resumed_from"] == 2
    assert res.rows[1]["output"] == {"solution": "#### 9"}


# ---------------------------------------------------------------------------
# Phrase: "for multi-task configs, apply resume separately per task output
#          file"
# Context: Resume.
# ---------------------------------------------------------------------------
def test_resume_is_per_task(run_tool, write_config, write_input, workdir):
    out_dir = workdir / "out"
    out_dir.mkdir()
    write_existing(str(out_dir / "gsm8k.jsonl"), [done_row(i)
                                                  for i in range(2)])
    write_existing(str(out_dir / "mmlu.jsonl"),
                   [{"input": {"question": "q0", "a": "1", "b": "2",
                               "c": "3", "d": "4", "answer": "A"},
                     "output": {"choice": "A"},
                     "result": {"passed": True, "extracted_answer": "A",
                                "attempts": 1},
                     "meta": None}])
    with MockAPI(always("A #### 5")) as api:
        cfg = write_config(multi_config(api.url,
                                        {"gsm8k": copy.deepcopy(GSM8K_TASK),
                                         "mmlu": copy.deepcopy(MMLU_TASK)}))
        a = write_input(rows_of(4), name="a.jsonl")
        b = write_input([{"question": f"q{i}", "a": "1", "b": "2", "c": "3",
                          "d": "4", "answer": "A"} for i in range(3)],
                        name="b.jsonl")
        res = run_tool(cfg, [f"gsm8k={a}", f"mmlu={b}"], output=str(out_dir),
                       extra=["--resume"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2 + 2          # gsm8k rows 2-3, mmlu rows 1-2
    assert len(res.rows_for("gsm8k")) == 4
    assert len(res.rows_for("mmlu")) == 3
    assert res.summary["total"] == 4

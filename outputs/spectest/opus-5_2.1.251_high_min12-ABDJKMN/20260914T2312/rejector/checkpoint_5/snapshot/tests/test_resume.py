"""Resume section: --resume skips already-complete leading rows."""

import json
import os

import pytest

import fake_api


def rows_of(n):
    return [{"question": "q%d" % i, "answer": "5"} for i in range(n)]


# ---------------------------------------------------------------------------
# Spec: "if `--resume` is set and the output file already exists, inspect the
#        existing output to determine how many input rows are already complete"
# Spec: "match by input row index; because outputs are written in input order,
#        the existing line count gives the number of leading rows to skip"
# Context: Resume.
# ---------------------------------------------------------------------------
def test_resume_skips_completed_leading_rows(run_cli, write_config,
                                             write_input, workdir):
    out = str(workdir / "results.jsonl")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        first = write_input(rows_of(3))
        run_cli("run", "--config", cfg, "--input", first, "--output", out,
                check=0)
        assert len(open(out).read().strip().splitlines()) == 3

        second = write_input(rows_of(5))
        before = api.call_count
        res = run_cli("run", "--config", cfg, "--input", second,
                      "--output", out, "--resume", output=out, check=0)
        assert api.call_count - before == 2

    assert [r["input"]["question"] for r in res.rows] == \
        ["q0", "q1", "q2", "q3", "q4"]


# ---------------------------------------------------------------------------
# Spec: "append new rows to the existing output file"
# Context: Resume.  The pre-existing lines are untouched.
# ---------------------------------------------------------------------------
def test_resume_appends_to_the_existing_file(run_cli, write_config,
                                             write_input, workdir):
    out = str(workdir / "results.jsonl")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        run_cli("run", "--config", cfg, "--input", write_input(rows_of(2)),
                "--output", out, check=0)
        original = open(out).read().strip().splitlines()

        run_cli("run", "--config", cfg, "--input", write_input(rows_of(4)),
                "--output", out, "--resume", output=out, check=0)
    lines = open(out).read().strip().splitlines()
    assert lines[:2] == original
    assert len(lines) == 4


# ---------------------------------------------------------------------------
# Spec: "the summary covers only newly processed rows and includes
#        `resumed_from`"
# Spec example: {"total": 50, "resumed_from": 50, "passed": 42, "failed": 8}
# Context: Resume.
# ---------------------------------------------------------------------------
def test_summary_covers_only_new_rows(run_cli, write_config, write_input,
                                      workdir):
    out = str(workdir / "results.jsonl")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        run_cli("run", "--config", cfg, "--input", write_input(rows_of(3)),
                "--output", out, check=0)
        res = run_cli("run", "--config", cfg, "--input",
                      write_input(rows_of(5)), "--output", out, "--resume",
                      output=out, check=0)
    summary = res.summary
    assert summary["resumed_from"] == 3
    assert summary["total"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["total_api_calls"] == 2


# ---------------------------------------------------------------------------
# Spec: "if `--resume` is set and the output file already exists"
# Context: Resume.  With no existing file nothing is skipped.
# ---------------------------------------------------------------------------
def test_resume_without_an_existing_output(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, rows=rows_of(3), extra=["--resume"], check=0)
    assert res.summary["resumed_from"] == 0
    assert res.summary["total"] == 3
    assert len(res.rows) == 3


# ---------------------------------------------------------------------------
# Spec: "--resume" is opt-in.
# Context: Resume.  Without the flag an existing output file is rewritten and
# no `resumed_from` appears.
# ---------------------------------------------------------------------------
def test_without_resume_the_output_is_rewritten(run_cli, write_config,
                                                write_input, workdir):
    out = str(workdir / "results.jsonl")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        run_cli("run", "--config", cfg, "--input", write_input(rows_of(3)),
                "--output", out, check=0)
        res = run_cli("run", "--config", cfg, "--input",
                      write_input(rows_of(3)), "--output", out, output=out,
                      check=0)
    assert len(res.rows) == 3
    assert "resumed_from" not in res.summary


# ---------------------------------------------------------------------------
# Spec: "for multi-task configs, apply resume separately per task output file"
# Context: Resume.
# ---------------------------------------------------------------------------
def test_resume_is_per_task(run_multi, workdir):
    inputs = {"gsm8k": rows_of(4),
              "mmlu": [{"question": "m%d" % i, "answer": "B"}
                       for i in range(4)]}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_multi(api, inputs={"gsm8k": rows_of(2),
                               "mmlu": [{"question": "m%d" % i, "answer": "B"}
                                        for i in range(3)]}, check=0)
        before = api.call_count
        res = run_multi(api, inputs=inputs, extra=["--resume"], check=0)
        assert api.call_count - before == 3       # 2 new gsm8k + 1 new mmlu
    assert len(res.task_rows("gsm8k")) == 4
    assert len(res.task_rows("mmlu")) == 4
    assert res.summary["resumed_from"] == 5
    assert res.summary["total"] == 3


# ---------------------------------------------------------------------------
# Spec: "when a prior output row represents an incomplete multi-solution or
#        rejection result with fewer passing solutions than `num_solutions`,
#        do not skip that row; reprocess it from scratch"
# Context: Resume.
# ---------------------------------------------------------------------------
def test_incomplete_multi_solution_row_is_reprocessed(run_cli, write_config,
                                                      write_input, workdir):
    out = str(workdir / "results.jsonl")
    partial = {"input": {"question": "q0", "answer": "5"},
               "output": [{"solution": "#### 5", "icl_setup": None}],
               "result": {"passed": 1, "failed": 0, "attempts": 1},
               "meta": []}
    with open(out, "w") as fh:
        fh.write(json.dumps(partial) + "\n")

    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url,
                            "num_solutions": 3,
                            "generation": {"scheme": "rejection",
                                           "temperature": 0.8}})
        res = run_cli("run", "--config", cfg, "--input",
                      write_input(rows_of(1)), "--output", out, "--resume",
                      output=out, check=0)
        assert api.call_count == 3
    assert len(res.rows) == 1
    assert len(res.rows[0]["output"]) == 3
    assert res.summary["resumed_from"] == 0
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "when a prior output row represents an incomplete ... result with
#        fewer passing solutions than `num_solutions`" -- a complete one is
#        still skipped.
# Context: Resume.
# ---------------------------------------------------------------------------
def test_complete_multi_solution_row_is_skipped(run_cli, write_config,
                                                write_input, workdir):
    out = str(workdir / "results.jsonl")
    complete = {"input": {"question": "q0", "answer": "5"},
                "output": [{"solution": "#### 5", "icl_setup": None},
                           {"solution": "#### 5", "icl_setup": None}],
                "result": {"passed": 2, "failed": 0, "attempts": 2},
                "meta": []}
    with open(out, "w") as fh:
        fh.write(json.dumps(complete) + "\n")

    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url,
                            "num_solutions": 2,
                            "generation": {"scheme": "rejection",
                                           "temperature": 0.8}})
        res = run_cli("run", "--config", cfg, "--input",
                      write_input(rows_of(2)), "--output", out, "--resume",
                      output=out, check=0)
        assert api.call_count <= 2       # only the second row is processed
    assert res.summary["resumed_from"] == 1
    assert res.summary["total"] == 1
    assert len(res.rows) == 2


# ---------------------------------------------------------------------------
# Spec: "do not skip that row; reprocess it from scratch"  (AMBIGUITIES T101)
# Context: Resume.  A failed greedy row is complete, so it is not retried.
# ---------------------------------------------------------------------------
def test_failed_greedy_row_is_not_reprocessed(run_cli, write_config,
                                              write_input, workdir):
    out = str(workdir / "results.jsonl")
    failed = {"input": {"question": "q0", "answer": "5"},
              "output": None,
              "result": {"passed": False, "extracted_answer": None,
                         "attempts": 1},
              "meta": {}}
    with open(out, "w") as fh:
        fh.write(json.dumps(failed) + "\n")

    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        res = run_cli("run", "--config", cfg, "--input",
                      write_input(rows_of(1)), "--output", out, "--resume",
                      output=out, check=0)
        assert api.call_count == 0
    assert res.summary["resumed_from"] == 1
    assert res.summary["total"] == 0
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Spec example: "If the output already has 500 lines, skip the first 500 input
#               rows and append new results after them."
# Context: Resume / Examples.  An output at least as long as the input leaves
# nothing to do.
# ---------------------------------------------------------------------------
def test_resume_with_nothing_left_to_do(run_cli, write_config, write_input,
                                        workdir):
    out = str(workdir / "results.jsonl")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        run_cli("run", "--config", cfg, "--input", write_input(rows_of(3)),
                "--output", out, check=0)
        before = api.call_count
        res = run_cli("run", "--config", cfg, "--input",
                      write_input(rows_of(3)), "--output", out, "--resume",
                      output=out, check=0)
        assert api.call_count == before
    assert res.summary["total"] == 0
    assert res.summary["resumed_from"] == 3
    assert len(res.rows) == 3

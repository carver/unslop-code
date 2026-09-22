"""`--resume`: skipping the leading rows an earlier run already completed."""

from __future__ import annotations

import json

from conftest import exact_match_task, make_config, make_multi_config

ROWS = [{"question": f"q{index}", "answer": "1"} for index in range(5)]


def done_row(row: dict, solutions: int = 1) -> str:
    """A finished greedy result row, as an earlier run would have written it."""
    return json.dumps(
        {
            "input": row,
            "output": {"solution": "#### 1"},
            "result": {"passed": True, "extracted_answer": "1", "attempts": 1},
            "meta": {"model": "gpt-4"},
        }
    )


def existing(rows: list[dict]) -> str:
    return "".join(done_row(row) + "\n" for row in rows)


# Spec: "if `--resume` is set and the output file already exists, inspect the
# existing output to determine how many input rows are already complete ...
# the existing line count gives the number of leading rows to skip."
def test_resume_skips_the_rows_already_written(server, run_cli):
    result = run_cli(
        make_config(server.url),
        ROWS,
        "--resume",
        files={"results.jsonl": existing(ROWS[:3])},
    )
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 2
    assert [row["input"] for row in result.rows] == ROWS


# Spec: "append new rows to the existing output file" -- the rows that were
# already there are left exactly as they were.
def test_existing_rows_are_left_untouched(server, run_cli):
    kept = existing(ROWS[:3])
    result = run_cli(
        make_config(server.url), ROWS, "--resume", files={"results.jsonl": kept}
    )
    assert result.output_path.read_text().startswith(kept)
    assert len(result.rows) == 5


# Spec: "the summary covers only newly processed rows and includes
# `resumed_from`."
def test_summary_counts_only_new_rows(server, run_cli):
    result = run_cli(
        make_config(server.url),
        ROWS,
        "--resume",
        files={"results.jsonl": existing(ROWS[:3])},
    )
    assert result.summary["total"] == 2
    assert result.summary["resumed_from"] == 3
    assert result.summary["passed"] + result.summary["failed"] == 2


# Spec: `--resume` with nothing to resume from behaves like a normal run.
def test_resume_without_an_existing_output(server, run_cli):
    result = run_cli(make_config(server.url), ROWS, "--resume")
    assert result.exit_code == 0, result.stderr
    assert result.summary["resumed_from"] == 0
    assert result.summary["total"] == 5
    assert server.call_count == 5


# Spec: an output that already covers every input leaves nothing to do. (T100)
def test_resume_with_everything_already_done(server, run_cli):
    result = run_cli(
        make_config(server.url),
        ROWS,
        "--resume",
        files={"results.jsonl": existing(ROWS)},
    )
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 0
    assert result.summary["total"] == 0
    assert result.summary["resumed_from"] == 5


# Spec: "for multi-task configs, apply resume separately per task output file."
def test_resume_is_per_task_output_file(server, run_multi):
    config = make_multi_config(
        server.url, {"gsm8k": exact_match_task(), "mmlu": exact_match_task()}
    )
    result = run_multi(
        config,
        {"gsm8k": ROWS, "mmlu": ROWS},
        "--resume",
        files={"results/gsm8k.jsonl": existing(ROWS[:4])},
    )
    assert result.exit_code == 0, result.stderr
    assert len(result.rows("gsm8k")) == 5
    assert len(result.rows("mmlu")) == 5
    assert server.call_count == 6
    assert result.summary["tasks"]["gsm8k"]["total"] == 1
    assert result.summary["tasks"]["mmlu"]["total"] == 5


# Spec: "when a prior output row represents an incomplete multi-solution or
# rejection result with fewer passing solutions than `num_solutions`, do not
# skip that row; reprocess it from scratch." (T99)
def test_incomplete_rejection_row_is_reprocessed(servers, run_cli):
    server = servers(contents=["#### 1"])
    failed = json.dumps(
        {
            "input": ROWS[1],
            "output": None,
            "result": {"passed": False, "extracted_answer": None, "attempts": 2},
            "meta": [],
        }
    )
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 2}
    )
    result = run_cli(
        config,
        ROWS[:3],
        "--resume",
        files={"results.jsonl": done_row(ROWS[0]) + "\n" + failed + "\n"},
    )
    assert result.exit_code == 0, result.stderr
    assert result.summary["resumed_from"] == 1
    assert len(result.rows) == 3
    assert [row["input"] for row in result.rows] == ROWS[:3]
    assert result.rows[1]["result"]["passed"] is True


# Spec: the same rule for a multi-solution row that holds fewer solutions than
# `num_solutions`.
def test_incomplete_multi_solution_row_is_reprocessed(servers, run_cli):
    server = servers(contents=["#### 1"])
    partial = json.dumps(
        {
            "input": ROWS[0],
            "output": [{"solution": "#### 1", "icl_setup": None}],
            "result": {"passed": 1, "failed": 2, "attempts": 3},
            "meta": [],
        }
    )
    config = make_config(
        server.url,
        num_solutions=2,
        generation={"scheme": "rejection", "temperature": 0.7},
    )
    result = run_cli(
        config, ROWS[:2], "--resume", files={"results.jsonl": partial + "\n"}
    )
    assert result.exit_code == 0, result.stderr
    assert result.summary["resumed_from"] == 0
    assert len(result.rows) == 2
    assert len(result.rows[0]["output"]) == 2


# Spec: "`python rejector.py run --config task.yaml --input data.jsonl
# --output results.jsonl --resume`" -- a run without the flag ignores whatever
# the output file holds and rewrites it.
def test_without_resume_the_output_is_rewritten(server, run_cli):
    result = run_cli(
        make_config(server.url), ROWS, files={"results.jsonl": existing(ROWS[:3])}
    )
    assert len(result.rows) == 5
    assert server.call_count == 5
    assert "resumed_from" not in result.summary

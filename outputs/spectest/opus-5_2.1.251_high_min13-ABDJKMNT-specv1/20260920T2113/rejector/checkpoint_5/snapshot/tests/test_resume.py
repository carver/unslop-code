"""`--resume`: skipping rows an earlier run already completed."""

from __future__ import annotations

import json

from tests.conftest import answering, multi_config, numbered_rows, read_jsonl, task_config


def done_row(question: str) -> dict:
    """An output row a previous run would have written for ``question``."""
    return {
        "input": {"question": question, "answer": question},
        "output": {"solution": f"#### {question}"},
        "result": {"passed": True, "extracted_answer": question, "attempts": 1},
        "meta": {"model": "gpt-4"},
    }


def seed(path, rows: list[dict]):
    """Pre-create an output file holding ``rows``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


# "if `--resume` is set and the output file already exists, inspect the existing
#  output to determine how many input rows are already complete"
# "the existing line count gives the number of leading rows to skip"
def test_leading_rows_are_skipped(cli, api):
    server = api(answering())
    seed(cli.tmp_path / "results.jsonl", [done_row("0"), done_row("1")])
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(5), "--resume")
    assert run.returncode == 0
    # arrival order of concurrent requests cannot be asserted (T20), only which
    # rows were sent at all
    assert sorted(body["messages"][-1]["content"] for body in server.log.bodies) == \
        ["2", "3", "4"]


# "append new rows to the existing output file"
def test_new_rows_are_appended(cli, api):
    server = api(answering())
    seed(cli.tmp_path / "results.jsonl", [done_row("0"), done_row("1")])
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(5), "--resume")
    assert [row["input"]["question"] for row in run.rows] == ["0", "1", "2", "3", "4"]
    assert run.rows[0] == done_row("0")


# "the summary covers only newly processed rows and includes `resumed_from`"
# '{"total": 50, "resumed_from": 50, "passed": 42, "failed": 8}'
def test_summary_covers_only_new_rows(cli, api):
    server = api(answering())
    seed(cli.tmp_path / "results.jsonl", [done_row(str(index)) for index in range(3)])
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(5), "--resume")
    summary = run.summary
    assert (summary["total"], summary["resumed_from"]) == (2, 3)
    assert (summary["passed"], summary["failed"]) == (2, 0)


# "if `--resume` is set and the output file already exists" - with no output file
# there is nothing to skip
def test_resume_without_an_output_file_processes_everything(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(3), "--resume")
    assert run.summary["resumed_from"] == 0
    assert run.summary["total"] == 3
    assert len(run.rows) == 3


# "If the output already has 500 lines, skip the first 500 input rows and append
#  new results after them." - and a run whose output is already complete sends
#  no requests at all
def test_complete_output_needs_no_requests(cli, api):
    server = api(answering())
    seed(cli.tmp_path / "results.jsonl", [done_row(str(index)) for index in range(3)])
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(3), "--resume")
    assert run.returncode == 0
    assert server.log.calls == []
    assert run.summary["total"] == 0
    assert run.summary["resumed_from"] == 3


# "for multi-task configs, apply resume separately per task output file"
def test_resume_applies_per_task_output_file(cli, api):
    from tests.conftest import SPEC_ROWS

    server = api(answering())
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url, "rpm": 600})
    config["tasks"]["gsm8k"]["generation"] = {"scheme": "greedy"}
    seed(cli.tmp_path / "results" / "gsm8k.jsonl", [done_row("0")])
    run = cli.run_multi(
        config,
        {"gsm8k": [SPEC_ROWS["gsm8k"]] * 3, "mmlu": [SPEC_ROWS["mmlu"]] * 2},
        "--resume",
    )
    assert run.returncode == 0
    assert len(run.task_rows("gsm8k")) == 3
    assert len(run.task_rows("mmlu")) == 2
    assert run.summary["tasks"]["gsm8k"]["resumed_from"] == 1
    assert run.summary["tasks"]["mmlu"]["resumed_from"] == 0
    assert run.summary["resumed_from"] == 1


# "when a prior output row represents an incomplete multi-solution or rejection
#  result with fewer passing solutions than `num_solutions`, do not skip that
#  row; reprocess it from scratch"
def test_incomplete_multi_solution_row_is_reprocessed(cli, api):
    server = api(answering())
    partial = {
        "input": {"question": "0", "answer": "0"},
        "output": [{"solution": "#### 0", "icl_setup": None}],
        "result": {"passed": 1, "failed": 0, "attempts": 1},
        "meta": [],
    }
    path = seed(cli.tmp_path / "results.jsonl", [partial])
    config = task_config(api_url=server.url, rpm=600, num_solutions=3,
                         generation={"scheme": "sample", "temperature": 0.7})
    run = cli.run(config, numbered_rows(2), "--resume")
    assert run.returncode == 0
    assert run.summary["resumed_from"] == 0
    assert [len(row["output"]) for row in read_jsonl(path)] == [3, 3]


# "when a prior output row represents an incomplete ... rejection result with
#  fewer passing solutions than `num_solutions`, do not skip that row"
def test_unfinished_rejection_row_is_reprocessed(cli, api):
    server = api(answering())
    empty = {"input": {"question": "0", "answer": "0"}, "output": None,
             "result": {"passed": False, "attempts": 1}, "meta": {}}
    path = seed(cli.tmp_path / "results.jsonl", [empty])
    config = task_config(api_url=server.url, rpm=600,
                         generation={"scheme": "rejection", "temperature": 0.7, "n": 2})
    run = cli.run(config, numbered_rows(2), "--resume")
    assert run.summary["resumed_from"] == 0
    assert [row["output"]["solution"] for row in read_jsonl(path)] == ["#### 0", "#### 1"]


# "match by input row index" - a complete multi-solution row is still skipped
def test_complete_multi_solution_row_is_skipped(cli, api):
    server = api(answering())
    complete = {
        "input": {"question": "0", "answer": "0"},
        "output": [{"solution": "#### 0", "icl_setup": None}] * 2,
        "result": {"passed": 2, "failed": 0, "attempts": 2},
        "meta": [],
    }
    seed(cli.tmp_path / "results.jsonl", [complete])
    config = task_config(api_url=server.url, rpm=600, num_solutions=2,
                         generation={"scheme": "sample", "temperature": 0.7})
    run = cli.run(config, numbered_rows(2), "--resume")
    assert run.summary["resumed_from"] == 1
    assert [body["messages"][-1]["content"] for body in server.log.bodies] == ["1", "1"]


# Without `--resume` the existing output file is replaced, as before
def test_without_resume_the_output_is_overwritten(cli, api):
    server = api(answering())
    seed(cli.tmp_path / "results.jsonl", [done_row("9")])
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(2))
    assert [row["input"]["question"] for row in run.rows] == ["0", "1"]
    assert "resumed_from" not in run.summary

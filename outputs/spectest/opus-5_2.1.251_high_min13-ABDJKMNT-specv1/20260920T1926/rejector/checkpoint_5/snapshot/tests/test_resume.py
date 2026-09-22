"""`--resume`: skipping rows an earlier run already completed."""

from __future__ import annotations

import json

from conftest import base_defaults, base_task, math_task, task_rows
from fake_api import FakeAPI, Reply, always, sequence

ROWS = [{"question": f"q{i}", "answer": "5"} for i in range(6)]


def prior(workdir, count: int, name: str = "out.jsonl"):
    """Write `count` finished output rows, as an interrupted run would leave."""
    path = workdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "input": ROWS[index],
                    "output": {"solution": "#### 5"},
                    "result": {"passed": True, "extracted_answer": "5", "attempts": 1},
                    "meta": {"model": "gpt-4"},
                }
            )
            + "\n"
            for index in range(count)
        )
    )
    return path


# Spec: "if --resume is set and the output file already exists, inspect the
# existing output to determine how many input rows are already complete" and
# "the existing line count gives the number of leading rows to skip".
# Context: Resume / Rules.
def test_existing_rows_are_skipped(write_config, write_input, run_cli, workdir):
    prior(workdir, 4)
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input(ROWS)
        run_cli(config, data, "--resume")
        assert api.call_count == 2


# Spec: "match by input row index; because outputs are written in input order"
# and "append new rows to the existing output file".
# Context: Resume / Rules.
def test_new_rows_are_appended_in_order(write_config, write_input, run_cli, workdir):
    prior(workdir, 4)
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input(ROWS)
        result = run_cli(config, data, "--resume")
    assert [row["input"]["question"] for row in result.rows] == [f"q{i}" for i in range(6)]


# Spec: "the summary covers only newly processed rows and includes
# resumed_from".
# Context: Resume / Rules and Example summary.
def test_summary_counts_only_new_rows(write_config, write_input, run_cli, workdir):
    prior(workdir, 4)
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input(ROWS)
        result = run_cli(config, data, "--resume")
    assert result.summary["total"] == 2
    assert result.summary["resumed_from"] == 4
    assert result.summary["passed"] == 2


# Spec: "if --resume is set and the output file already exists" — without an
# existing file the run starts from the beginning.
# Context: Resume / Rules.
def test_resume_without_existing_output_runs_everything(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input(ROWS)
        result = run_cli(config, data, "--resume")
        assert api.call_count == 6
    assert result.summary["resumed_from"] == 0


# Spec: "--resume" is opt-in; without it an existing output file is replaced.
# Context: Resume / CLI flag.
def test_without_resume_the_output_is_rewritten(write_config, write_input, run_cli, workdir):
    prior(workdir, 4)
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input(ROWS)
        result = run_cli(config, data)
        assert api.call_count == 6
    assert len(result.rows) == 6
    assert "resumed_from" not in result.summary


# Spec: "for multi-task configs, apply resume separately per task output file".
# Context: Resume / Rules.
def test_resume_is_per_task_output_file(write_yaml, write_inputs, run_args, workdir):
    results = workdir / "results"
    prior(results, 5, name="a.jsonl")
    with FakeAPI(responder=always("#### 5")) as api:
        document = {
            "defaults": base_defaults(api.url),
            "tasks": {"a": math_task(), "b": math_task()},
        }
        config = write_yaml(document)
        data = write_inputs({"a": ROWS, "b": ROWS})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(results), "--resume",
        )
        assert api.call_count == 1 + 6
    assert len(task_rows(result, "a")) == 6
    assert len(task_rows(result, "b")) == 6
    assert result.summary["resumed_from"] == 5


# Spec: "when a prior output row represents an incomplete multi-solution or
# rejection result with fewer passing solutions than num_solutions, do not
# skip that row; reprocess it from scratch."
# Context: Resume / Rules.
def test_incomplete_multi_solution_row_is_reprocessed(write_config, write_input, run_cli, workdir):
    (workdir / "out.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "input": ROWS[index],
                    "output": [{"solution": "#### 5", "icl_setup": None}] * solutions,
                    "result": {"passed": solutions, "failed": 0, "attempts": solutions},
                    "meta": [],
                }
            )
            + "\n"
            for index, solutions in enumerate([3, 3, 1])
        )
    )
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url, num_solutions=3)
        task["generation"] = {"scheme": "sample", "temperature": 0.7}
        config = write_config(task)
        data = write_input(ROWS)
        result = run_cli(config, data, "--resume")
    # Rows 0 and 1 are complete; row 2 onwards is reprocessed.
    assert result.summary["resumed_from"] == 2
    assert result.summary["total"] == 4
    assert len(result.rows) == 6


# Spec: "when a prior output row represents an incomplete ... rejection result
# with fewer passing solutions than num_solutions, do not skip that row".
# Context: Resume / Rules; a rejection row that never passed has null output.
def test_incomplete_rejection_row_is_reprocessed(write_config, write_input, run_cli, workdir):
    (workdir / "out.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "input": ROWS[index],
                    "output": output,
                    "result": {"passed": output is not None, "attempts": 3},
                    "meta": [],
                }
            )
            + "\n"
            for index, output in enumerate([{"solution": "#### 5"}, None])
        )
    )
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3}
        config = write_config(task)
        data = write_input(ROWS)
        result = run_cli(config, data, "--resume")
    assert result.summary["resumed_from"] == 1
    assert result.summary["total"] == 5


# Spec: "If the output already has 500 lines, skip the first 500 input rows and
# append new results after them."
# Context: Examples / Resume after interruption.
def test_appended_rows_follow_the_existing_ones(write_config, write_input, run_cli, workdir):
    prior(workdir, 4)
    with FakeAPI(responder=sequence([Reply(content="#### 9")])) as api:
        config = write_config(base_task(api.url))
        data = write_input(ROWS)
        result = run_cli(config, data, "--resume")
    assert [row["output"]["solution"] for row in result.rows[:4]] == ["#### 5"] * 4
    assert [row["output"]["solution"] for row in result.rows[4:]] == ["#### 9"] * 2

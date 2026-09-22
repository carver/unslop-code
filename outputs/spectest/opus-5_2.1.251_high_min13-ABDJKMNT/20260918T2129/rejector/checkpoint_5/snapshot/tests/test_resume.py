"""`--resume`: skipping rows an earlier run already completed."""

from __future__ import annotations

import json

from fake_server import FakeAPIServer, Reply, always, completion, user_of
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config


def _rows(write_input, count, name="input.jsonl"):
    return write_input([{"question": f"q{i}", "answer": "5"} for i in range(count)], name=name)


def _echo(payload, index):
    return Reply(completion(f"#### {user_of(payload)}"))


# Spec: "if `--resume` is set and the output file already exists, inspect the
# existing output to determine how many input rows are already complete"
def test_resume_skips_rows_already_written(write_config, write_input, run_cli):
    with FakeAPIServer(_echo) as api:
        config = write_config(base_config(api.url, evaluation=None))
        first = run_cli(config, _rows(write_input, 5))
        assert len(first.rows) == 5
        calls_before = len(api.requests)
        second = run_cli(config, _rows(write_input, 12), "--resume")
        new_calls = len(api.requests) - calls_before

    assert new_calls == 7
    assert second.summary["total"] == 7


# Spec: "match by input row index; because outputs are written in input
# order, the existing line count gives the number of leading rows to skip"
def test_appended_rows_continue_the_input_order(write_config, write_input, run_cli):
    with FakeAPIServer(_echo) as api:
        config = write_config(base_config(api.url, evaluation=None))
        run_cli(config, _rows(write_input, 5))
        second = run_cli(config, _rows(write_input, 12), "--resume")

    assert [row["input"]["question"] for row in second.rows] == [f"q{i}" for i in range(12)]


# Spec: "append new rows to the existing output file"
def test_existing_rows_are_preserved_verbatim(write_config, write_input, run_cli):
    with FakeAPIServer(_echo) as api:
        config = write_config(base_config(api.url, evaluation=None))
        first = run_cli(config, _rows(write_input, 3))
        original = first.output_path.read_text()
        second = run_cli(config, _rows(write_input, 6), "--resume")

    assert second.output_path.read_text().startswith(original)


# Spec: "the summary covers only newly processed rows and includes
# `resumed_from`"
def test_summary_reports_what_was_skipped(write_config, write_input, run_cli):
    with FakeAPIServer(_echo) as api:
        config = write_config(base_config(api.url, evaluation=None))
        run_cli(config, _rows(write_input, 4))
        second = run_cli(config, _rows(write_input, 10), "--resume")

    assert second.summary["resumed_from"] == 4
    assert second.summary["total"] == 6


# Spec: "--resume" with no prior output file processes everything (T95)
def test_resume_without_an_existing_file_processes_every_row(write_config, write_input, run_cli):
    with FakeAPIServer(_echo) as api:
        config = write_config(base_config(api.url, evaluation=None))
        result = run_cli(config, _rows(write_input, 3), "--resume")

    assert result.summary["resumed_from"] == 0
    assert result.summary["total"] == 3


# Spec: "resumed_from" belongs to resumed runs only
def test_plain_runs_have_no_resumed_from(write_config, write_input, run_cli):
    with FakeAPIServer(_echo) as api:
        config = write_config(base_config(api.url, evaluation=None))
        result = run_cli(config, _rows(write_input, 2))

    assert "resumed_from" not in result.summary


# Spec: "when a prior output row represents an incomplete multi-solution or
# rejection result with fewer passing solutions than `num_solutions`, do not
# skip that row; reprocess it from scratch"
def test_an_incomplete_multi_solution_row_is_reprocessed(write_config, write_input, run_cli):
    config_map = base_config("http://x", num_solutions=3, evaluation=None)
    config_map["task"]["generation"] = {"scheme": "sample", "temperature": 0.7}
    rows = _rows(write_input, 3)

    complete = {"input": {"question": "q0"}, "output": [{"solution": "a"}] * 3,
                "result": {"passed": 3, "failed": 0, "attempts": 3}, "meta": []}
    partial = {"input": {"question": "q1"}, "output": [{"solution": "a"}],
               "result": {"passed": 1, "failed": 2, "attempts": 3}, "meta": []}

    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        output = config.parent / "results.jsonl"
        output.write_text(json.dumps(complete) + "\n" + json.dumps(partial) + "\n")
        result = run_cli(config, rows, "--resume")

    assert result.summary["resumed_from"] == 1
    assert result.summary["total"] == 2
    assert [row["input"]["question"] for row in result.rows] == ["q0", "q1", "q2"]


# Spec: "do not skip that row; reprocess it from scratch" - the stale line is
# replaced rather than duplicated (T96)
def test_the_reprocessed_row_replaces_its_stale_line(write_config, write_input, run_cli):
    config_map = base_config("http://x", num_solutions=2, evaluation=None)
    config_map["task"]["generation"] = {"scheme": "sample", "temperature": 0.7}
    partial = {"input": {"question": "q0"}, "output": [{"solution": "stale"}],
               "result": {"passed": 1, "failed": 1, "attempts": 2}, "meta": []}

    with FakeAPIServer(always("fresh")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        output = config.parent / "results.jsonl"
        output.write_text(json.dumps(partial) + "\n")
        result = run_cli(config, _rows(write_input, 1), "--resume")

    assert len(result.rows) == 1
    assert [entry["solution"] for entry in result.rows[0]["output"]] == ["fresh", "fresh"]


# Spec: "an incomplete ... rejection result" - a single-solution rejection row
# that kept nothing is reprocessed (T94)
def test_an_empty_rejection_row_is_reprocessed(write_config, write_input, run_cli):
    config_map = base_config("http://x")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 2}
    stale = {"input": {"question": "q0"}, "output": None,
             "result": {"passed": False, "extracted_answer": None, "attempts": 2}, "meta": []}

    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        output = config.parent / "results.jsonl"
        output.write_text(json.dumps(stale) + "\n")
        result = run_cli(config, _rows(write_input, 1), "--resume")

    assert result.summary["resumed_from"] == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: greedy has no retry budget, so a failed greedy row stays skipped
# (T94)
def test_a_failed_greedy_row_is_not_reprocessed(write_config, write_input, run_cli):
    stale = {"input": {"question": "q0"}, "output": None,
             "result": {"passed": False, "extracted_answer": None, "attempts": 1}, "meta": []}

    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        output = config.parent / "results.jsonl"
        output.write_text(json.dumps(stale) + "\n")
        result = run_cli(config, _rows(write_input, 1), "--resume")
        calls = len(api.requests)

    assert calls == 0
    assert result.summary["resumed_from"] == 1


# Spec: "for multi-task configs, apply resume separately per task output file"
def test_resume_is_per_task(write_config, write_input, run_argv):
    def responder(payload, index):
        from fake_server import system_of
        return Reply(completion("#### 5" if "math" in system_of(payload) else "B"))

    with FakeAPIServer(responder) as api:
        config = write_config(multi_config(api.url, {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK}))
        gsm8k = write_input([{"question": f"q{i}", "answer": "5"} for i in range(4)], name="gsm8k.jsonl")
        mmlu_rows = [
            {"question": f"q{i}", "a": "1", "b": "2", "c": "3", "d": "4", "answer": "B"}
            for i in range(4)
        ]
        mmlu = write_input(mmlu_rows, name="mmlu.jsonl")
        args = ("--config", config, "--input", f"gsm8k={gsm8k}", "--input", f"mmlu={mmlu}")
        run_argv(*args)
        # Drop two lines from one task's file only; the other stays complete.
        partial = run_argv(*args, "--resume")
        gsm8k_file = partial.output_path / "gsm8k.jsonl"
        gsm8k_file.write_text("".join(gsm8k_file.read_text().splitlines(keepends=True)[:2]))
        second = run_argv(*args, "--resume")

    assert second.summary["tasks"]["gsm8k"]["resumed_from"] == 2
    assert second.summary["tasks"]["mmlu"]["resumed_from"] == 4
    assert second.summary["resumed_from"] == 6
    assert len(second.rows_of(partial.output_path / "gsm8k.jsonl")) == 4

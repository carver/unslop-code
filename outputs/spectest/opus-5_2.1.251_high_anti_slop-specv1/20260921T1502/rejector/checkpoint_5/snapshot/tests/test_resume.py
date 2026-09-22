"""Resuming a run over the rows an earlier one already wrote."""

import json

from conftest import read_records, write_rows

TASK = {
    "name": "math_solve",
    "model": "gpt-4",
    "prompt": {"user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 64},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}

ROWS = [{"question": f"q{index}", "answer": "5"} for index in range(5)]


def written(index):
    """An output row for `ROWS[index]`, as an earlier run would have left it."""
    return {
        "input": ROWS[index],
        "output": {"solution": "#### 5"},
        "result": {"passed": True, "extracted_answer": "5", "attempts": 1},
        "meta": {"model": "gpt-4", "prompt_tokens": 10, "completion_tokens": 5},
    }


def test_resume_skips_the_rows_already_written(tmp_path, cli, api):
    write_rows(tmp_path / "out.jsonl", [written(0), written(1)])
    url, state = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url}, ROWS, "--resume")

    assert len(state.calls) == 3
    assert run.summary["resumed_from"] == 2
    assert run.summary["total"] == 3
    assert [record["input"] for record in run.records] == ROWS


def test_resume_without_an_existing_output_runs_everything(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url}, ROWS, "--resume")

    assert run.summary["resumed_from"] == 0
    assert run.summary["total"] == 5


def test_a_finished_run_resumes_into_nothing(tmp_path, cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    cli({**TASK, "api_url": url}, ROWS)
    run = cli({**TASK, "api_url": url}, ROWS, "--resume")

    assert run.summary == {**run.summary, "total": 0, "resumed_from": 5}
    assert len(read_records(tmp_path / "out.jsonl")) == 5


def test_an_incomplete_rejection_row_is_produced_again(tmp_path, cli, api):
    short = {**written(1), "output": None, "result": {"passed": False, "attempts": 2}}
    write_rows(tmp_path / "out.jsonl", [written(0), short])
    url, state = api(lambda payload, call: "#### 5")
    run = cli(
        {**TASK, "api_url": url, "generation": {"scheme": "rejection", "temperature": 0.7, "n": 2}},
        ROWS,
        "--resume",
    )

    # The row that kept no solution is run again, along with the three after it.
    assert len(state.calls) == 4
    assert run.summary["resumed_from"] == 1
    assert [record["input"] for record in run.records] == ROWS


def test_an_incomplete_multi_solution_row_is_produced_again(tmp_path, cli, api):
    partial = {
        "input": ROWS[0],
        "output": [{"solution": "#### 5", "icl_setup": None}],
        "result": {"passed": 1, "failed": 0, "attempts": 1},
        "meta": [],
    }
    write_rows(tmp_path / "out.jsonl", [partial])
    url, _ = api(lambda payload, call: "#### 5")
    run = cli(
        {
            **TASK,
            "api_url": url,
            "num_solutions": 2,
            "generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64},
        },
        ROWS,
        "--resume",
    )

    assert run.summary["resumed_from"] == 0
    assert len(run.records) == 5
    assert len(run.records[0]["output"]) == 2


def test_resume_applies_to_each_output_file_of_a_multi_config(tmp_path, cli, api):
    url, state = api(lambda payload, call: "#### 5")
    document = {
        "defaults": {"api_url": url, "model": "gpt-4"},
        "tasks": {
            "first": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy"},
                "output_field": "solution",
            },
            "second": {
                "prompt": {"user": "{question}"},
                "generation": {"scheme": "greedy"},
                "output_field": "solution",
            },
        },
    }
    (tmp_path / "results").mkdir()
    write_rows(tmp_path / "results" / "first.jsonl", [written(0), written(1)])
    rows = {"first": ROWS, "second": ROWS}
    run = cli(document, rows, "--resume", multi=True)

    assert run.summary["tasks"]["first"]["resumed_from"] == 2
    assert run.summary["tasks"]["second"]["resumed_from"] == 0
    assert run.summary["resumed_from"] == 2
    assert len(state.calls) == 8
    assert len(read_records(tmp_path / "results" / "first.jsonl")) == 5


def test_a_run_without_resume_reports_no_resume_point(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url}, ROWS)

    assert "resumed_from" not in run.summary


def test_appended_rows_are_valid_json_lines(tmp_path, cli, api):
    write_rows(tmp_path / "out.jsonl", [written(0)])
    url, _ = api(lambda payload, call: "#### 5")
    cli({**TASK, "api_url": url}, ROWS, "--resume")

    lines = (tmp_path / "out.jsonl").read_text().splitlines()
    assert len(lines) == 5 and all(json.loads(line)["input"] for line in lines)

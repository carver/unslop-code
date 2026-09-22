"""End-to-end runs that pick up where an interrupted run left off."""

import json

import yaml
from conftest import read_results, run_cli, write_jsonl

ROWS = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(12)]
EVALUATION = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}


def write_task(tmp_path, api_url, **extra):
    task = {
        "name": "mock_task",
        "api_url": api_url,
        "model": "gpt-4",
        "rate_limits": {"rpm": 600},
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
        "generation": {"scheme": "greedy", "max_tokens": 64},
        "evaluation": EVALUATION,
        "output_field": "solution",
        **extra,
    }
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def write_multi_config(tmp_path, api_url):
    defaults = {
        "api_url": api_url,
        "model": "gpt-4",
        "rate_limits": {"rpm": 600},
        "generation": {"scheme": "greedy", "max_tokens": 64},
        "evaluation": EVALUATION,
        "output_field": "solution",
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
    }
    tasks = {"first": {}, "second": {}}
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump({"defaults": defaults, "tasks": tasks}))
    return path


def run_task(config, tmp_path, *extra, rows=ROWS):
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    output = tmp_path / "out.jsonl"
    process = run_cli("--config", config, "--input", data, "--output", output, *extra)
    assert process.returncode == 0, process.stderr
    return output, json.loads(process.stdout)


def keep_first(output, lines):
    """Leave only the first `lines` results, as an interrupted run would."""
    kept = output.read_text().splitlines()[:lines]
    output.write_text("".join(line + "\n" for line in kept))


def test_a_resumed_run_appends_the_rows_that_are_left(tmp_path, server):
    config = write_task(tmp_path, server())
    output, _ = run_task(config, tmp_path)
    keep_first(output, 5)

    _, summary = run_task(config, tmp_path, "--resume")

    results = read_results(output)
    assert [result["input"] for result in results] == ROWS
    assert summary["resumed_from"] == 5
    assert summary["total"] == 7, "the summary covers only the new rows"
    assert summary["total_api_calls"] == 7


def test_resuming_a_finished_run_does_nothing(tmp_path, server):
    config = write_task(tmp_path, server())
    output, _ = run_task(config, tmp_path)

    _, summary = run_task(config, tmp_path, "--resume")

    assert len(read_results(output)) == len(ROWS)
    assert (summary["total"], summary["resumed_from"]) == (0, len(ROWS))


def test_resuming_without_an_earlier_run_starts_from_scratch(tmp_path, server):
    config = write_task(tmp_path, server())
    output, summary = run_task(config, tmp_path, "--resume")

    assert len(read_results(output)) == len(ROWS)
    assert (summary["total"], summary["resumed_from"]) == (len(ROWS), 0)


def test_a_row_short_of_its_solutions_is_run_again(tmp_path, server):
    config = write_task(tmp_path, server(), num_solutions=3,
                        generation={"scheme": "sample", "temperature": 0.7, "max_tokens": 64})
    output, _ = run_task(config, tmp_path)
    records = read_results(output)
    records[4]["output"] = records[4]["output"][:1]
    output.write_text("".join(json.dumps(record) + "\n" for record in records[:8]))

    _, summary = run_task(config, tmp_path, "--resume")

    results = read_results(output)
    assert [result["input"] for result in results] == ROWS
    assert all(len(result["output"]) == 3 for result in results)
    assert summary["resumed_from"] == 4


def test_each_task_of_a_multi_task_run_resumes_on_its_own(tmp_path, server):
    config = write_multi_config(tmp_path, server())
    data = write_jsonl(tmp_path / "data.jsonl", ROWS)
    outputs = tmp_path / "results"
    arguments = ("--config", config, "--input", f"first={data}", "--input", f"second={data}",
                 "--output", outputs)
    assert run_cli(*arguments).returncode == 0
    keep_first(outputs / "first.jsonl", 9)
    keep_first(outputs / "second.jsonl", 2)

    process = run_cli(*arguments, "--resume")
    assert process.returncode == 0, process.stderr

    summary = json.loads(process.stdout)
    assert summary["resumed_from"] == 11
    assert summary["tasks"]["first"]["total"] == 3
    assert summary["tasks"]["second"]["total"] == 10
    for name in ("first", "second"):
        assert [result["input"] for result in read_results(outputs / f"{name}.jsonl")] == ROWS

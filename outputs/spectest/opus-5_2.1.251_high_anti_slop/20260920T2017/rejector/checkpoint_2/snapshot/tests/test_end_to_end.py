"""End-to-end CLI runs of a single-task config against the mock server."""

import json

import yaml
from conftest import read_results, run_cli, write_jsonl

ROWS = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(12)]


def write_task(tmp_path, api_url, generation=None, evaluation="default", rpm=600):
    task = {
        "name": "mock_task",
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": rpm,
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
        "generation": generation or {"scheme": "greedy", "max_tokens": 64},
        "output_field": "solution",
    }
    if evaluation == "default":
        evaluation = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}
    if evaluation is not None:
        task["evaluation"] = evaluation
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def write_input(tmp_path, rows=ROWS):
    return write_jsonl(tmp_path / "data.jsonl", rows)


def run_task(config, data, output, *extra):
    return run_cli("--config", config, "--input", data, "--output", output, *extra)


def test_greedy_run(tmp_path, server):
    config = write_task(tmp_path, server())
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output)

    assert process.returncode == 0, process.stderr
    results = read_results(output)
    assert [result["input"] for result in results] == ROWS
    assert all(result["result"] == {"passed": True, "extracted_answer": row["answer"], "attempts": 1}
               for result, row in zip(results, ROWS))
    assert results[0]["output"] == {"solution": "Working it out.\n#### 1"}
    assert results[0]["meta"]["model"] == "gpt-4"
    assert results[0]["meta"]["finish_reason"] == "stop"
    assert results[0]["meta"]["latency_ms"] >= 0

    summary = json.loads(process.stdout)
    assert summary["total"] == summary["passed"] == len(ROWS)
    assert summary["failed"] == 0
    assert summary["total_api_calls"] == len(ROWS)
    assert summary["total_prompt_tokens"] == 10 * len(ROWS)
    assert summary["total_completion_tokens"] == 5 * len(ROWS)
    assert "tasks" not in summary, "a single-task run keeps the part 1 summary"


def test_retries_do_not_change_logical_attempts(tmp_path, server):
    config = write_task(tmp_path, server("--fail-500", "3"))
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output)

    assert process.returncode == 0, process.stderr
    results = read_results(output)
    assert all(result["result"]["attempts"] == 1 for result in results)
    assert all(result["output"] is not None for result in results)
    assert json.loads(process.stdout)["total_api_calls"] == len(ROWS) + 3


def test_rows_fail_after_exhausting_retries(tmp_path, server):
    config = write_task(tmp_path, server("--always-500"))
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output)

    assert process.returncode == 0, process.stderr
    results = read_results(output)
    assert all(result["output"] is None and result["meta"] is None for result in results)
    assert all(result["result"] == {"passed": False, "extracted_answer": None, "attempts": 1}
               for result in results)

    summary = json.loads(process.stdout)
    assert summary["failed"] == len(ROWS)
    assert summary["passed"] == 0
    assert summary["total_api_calls"] == 3 * len(ROWS)


def test_rejection_keeps_the_first_passing_attempt(tmp_path, server):
    generation = {"scheme": "rejection", "temperature": 0.8, "max_tokens": 64, "n": 5}
    config = write_task(tmp_path, server("--pass-after", "3"), generation=generation)
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output)

    assert process.returncode == 0, process.stderr
    result = read_results(output)[0]
    assert result["result"] == {"passed": True, "extracted_answer": "1", "attempts": 3}
    assert len(result["meta"]) == 3
    assert json.loads(process.stdout)["total_api_calls"] == 3 * len(ROWS)


def test_rejection_gives_up_after_n_attempts(tmp_path, server):
    generation = {"scheme": "rejection", "temperature": 0.8, "max_tokens": 64, "n": 2}
    config = write_task(tmp_path, server("--pass-after", "9"), generation=generation)
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output)

    assert process.returncode == 0, process.stderr
    result = read_results(output)[0]
    assert result["output"] is None
    assert result["result"] == {"passed": False, "extracted_answer": None, "attempts": 2}
    assert len(result["meta"]) == 2
    assert json.loads(process.stdout)["failed"] == len(ROWS)


def test_run_without_evaluation_reports_null_pass(tmp_path, server):
    config = write_task(tmp_path, server(), evaluation=None)
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output)

    assert process.returncode == 0, process.stderr
    result = read_results(output)[0]
    assert result["result"]["passed"] is None
    assert result["result"]["extracted_answer"] is None
    assert json.loads(process.stdout)["passed"] == len(ROWS)


def test_cli_overrides_win_over_the_config(tmp_path, server):
    config = write_task(tmp_path, "http://127.0.0.1:1")
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path), output,
                       "--api-url", server(), "--scheme", "sample", "--temperature", "0.7",
                       "--model", "override-model", "--rpm", "300", "--max-tokens", "32")

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["meta"]["model"] == "override-model"


def test_missing_prompt_field_exits_with_code_1(tmp_path, server):
    config = write_task(tmp_path, server())
    output = tmp_path / "out.jsonl"
    process = run_task(config, write_input(tmp_path, [{"text": "hello"}]), output)

    assert process.returncode == 1
    assert "row 0" in process.stderr and "question" in process.stderr
    assert not output.exists()


def test_invalid_config_exits_with_code_1(tmp_path, server):
    config = write_task(tmp_path, server(), generation={"scheme": "sample", "temperature": 0.0})
    process = run_task(config, write_input(tmp_path), tmp_path / "out.jsonl")

    assert process.returncode == 1
    assert "temperature" in process.stderr


def test_throughput_uses_the_request_budget(tmp_path, server):
    """The server serves 600 requests/minute; the run should get close to that."""
    rows = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(60)]
    config = write_task(tmp_path, server(workers=10, delay=1.0), rpm=600)
    process = run_task(config, write_input(tmp_path, rows), tmp_path / "out.jsonl")

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["throughput_rpm"] >= 0.8 * 600, summary

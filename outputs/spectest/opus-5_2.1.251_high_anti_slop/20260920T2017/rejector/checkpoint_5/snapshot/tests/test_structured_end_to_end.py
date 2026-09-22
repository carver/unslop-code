"""End-to-end runs of a task whose responses must satisfy an `output_schema`."""

import json

import yaml
from conftest import read_results, run_cli, write_jsonl

SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}
PAYLOAD = {"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}


def question(payload=None):
    """A row whose response is `payload` as JSON, or prose when it has none."""
    return "Emit " + (f"JSON={json.dumps(payload)}" if payload else "an explanation")


def write_task(tmp_path, api_url, generation=None, evaluation=None, schema=SCHEMA):
    task = {
        "name": "code_gen",
        "api_url": api_url,
        "model": "gpt-4",
        "rate_limits": {"rpm": 600},
        "prompt": {"system": "Answer with JSON.", "user": "{question}"},
        "generation": generation or {"scheme": "greedy", "max_tokens": 64},
        "output_schema": schema,
        "output_field": "code",
    }
    if evaluation is not None:
        task["evaluation"] = evaluation
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def run_task(config, rows, tmp_path, *extra):
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    output = tmp_path / "out.jsonl"
    process = run_cli("--config", config, "--input", data, "--output", output, *extra)
    assert process.returncode == 0, process.stderr
    return read_results(output), json.loads(process.stdout)


def test_a_valid_response_is_stored_parsed(tmp_path, server):
    config = write_task(tmp_path, server())
    results, _ = run_task(config, [{"question": question(PAYLOAD)}], tmp_path)

    assert results[0]["output"] == {"code": PAYLOAD}
    assert results[0]["result"]["passed"] is True
    assert results[0]["result"]["schema_valid"] is True
    assert "schema_error" not in results[0]["result"]


def test_a_response_that_is_not_json_fails_the_row(tmp_path, server):
    config = write_task(tmp_path, server())
    results, summary = run_task(config, [{"question": question()}], tmp_path)

    assert results[0]["output"] is None
    assert results[0]["result"]["passed"] is False
    assert results[0]["result"]["schema_valid"] is False
    assert results[0]["result"]["schema_error"].startswith("Invalid JSON")
    assert summary["failed"] == 1


def test_a_missing_field_is_reported_on_the_row(tmp_path, server):
    config = write_task(tmp_path, server())
    results, _ = run_task(config, [{"question": question({"code": "x"})}], tmp_path)

    assert results[0]["output"] is None
    assert results[0]["result"]["schema_error"] == "Missing required field: explanation"


def test_rejection_retries_until_the_schema_is_satisfied(tmp_path, server):
    """The mock answers with prose until its third attempt at a prompt."""
    generation = {"scheme": "rejection", "temperature": 0.8, "max_tokens": 64, "n": 5}
    config = write_task(tmp_path, server("--pass-after", "3"), generation=generation)
    results, summary = run_task(config, [{"question": question(PAYLOAD)}], tmp_path)

    assert results[0]["output"] == {"code": PAYLOAD}
    assert results[0]["result"] == {
        "passed": True,
        "extracted_answer": None,
        "attempts": 3,
        "schema_valid": True,
    }
    assert summary["total_api_calls"] == 3


def test_rejection_gives_up_when_no_attempt_validates(tmp_path, server):
    generation = {"scheme": "rejection", "temperature": 0.8, "max_tokens": 64, "n": 2}
    config = write_task(tmp_path, server("--pass-after", "9"), generation=generation)
    results, summary = run_task(config, [{"question": question(PAYLOAD)}], tmp_path)

    assert results[0]["output"] is None
    assert results[0]["result"]["passed"] is False
    assert results[0]["result"]["attempts"] == 2
    assert summary["failed"] == 1


def test_a_valid_response_is_still_judged(tmp_path, server):
    evaluation = {"type": "contains", "answer_field": "answer"}
    config = write_task(tmp_path, server(), evaluation=evaluation)
    rows = [{"question": question(PAYLOAD), "answer": "return a + b"},
            {"question": question(PAYLOAD), "answer": "not in the response"}]
    results, summary = run_task(config, rows, tmp_path)

    assert [result["result"]["passed"] for result in results] == [True, False]
    assert all(result["result"]["schema_valid"] for result in results)
    assert summary["passed"] == 1


def test_a_schema_failure_skips_the_evaluation(tmp_path, server):
    """A judge is never asked about a response the schema already rejected."""
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {"system": "Score it.", "user": "Rate {__response__}"},
        "threshold": 7,
    }
    config = write_task(tmp_path, server(), evaluation=evaluation)
    results, summary = run_task(config, [{"question": question()}], tmp_path)

    assert results[0]["result"]["schema_valid"] is False
    assert results[0]["result"]["judge_score"] is None
    assert summary["total_api_calls"] == 1, "the generation only"

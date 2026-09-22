"""End-to-end CLI runs of a multi-task config against the mock server."""

import json

import yaml
from conftest import read_results, run_cli, write_jsonl

MATH_ROWS = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(4)]
CHOICE_ROWS = [{"question": "Capital? ANSWER=B", "answer": "B"},
               {"question": "Colour? ANSWER=C", "answer": "D"}]
REVIEW_ROWS = [{"prompt_text": "Describe a tree", "criteria": "clarity", "score": 8},
               {"prompt_text": "Describe a rock", "criteria": "clarity", "score": 3}]
CODE_ROWS = [{"problem": "say ANSWER=PASS", "test_code": "echo '{__response__}' | grep -q PASS"},
             {"problem": "say ANSWER=NOPE", "test_code": "echo '{__response__}' | grep -q PASS"}]

TASKS = {
    "math": {
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    },
    "choice": {
        "prompt": {"system": "Answer with a letter.", "user": "{question}"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
        "output_field": "choice",
    },
    "review": {
        "prompt": {"system": "Write a response.", "user": "{prompt_text}"},
        "evaluation": {
            "type": "llm_judge",
            # The mock server echoes the ANSWER marker, so the row picks its score.
            "judge_prompt": {"system": "Rate it 1-10.",
                             "user": "Rate:\n{__response__}\nCriteria: {criteria}\nANSWER={score}"},
            "threshold": 7,
            "extract": "first_number",
        },
        "output_field": "response",
    },
    "code": {
        "prompt": {"system": "Write code.", "user": "{problem}"},
        "evaluation": {"type": "script", "command_template": "{test_code}", "success_exit_code": 0},
        "output_field": "code",
    },
}
ROWS_BY_TASK = {"math": MATH_ROWS, "choice": CHOICE_ROWS, "review": REVIEW_ROWS, "code": CODE_ROWS}


def write_config(tmp_path, api_url, tasks=TASKS):
    document = {
        "defaults": {
            "api_url": api_url,
            "model": "gpt-4",
            "rpm": 600,
            "generation": {"scheme": "greedy", "max_tokens": 64},
        },
        "tasks": tasks,
    }
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


def write_inputs(tmp_path, names=ROWS_BY_TASK):
    """One `<task>.jsonl` per named task, in their own directory."""
    directory = tmp_path / "data"
    directory.mkdir(exist_ok=True)
    return {name: write_jsonl(directory / f"{name}.jsonl", ROWS_BY_TASK[name]) for name in names}


def input_flags(inputs):
    return [flag for name, path in inputs.items() for flag in ("--input", f"{name}={path}")]


def test_every_task_writes_its_own_output_file(tmp_path, server):
    config = write_config(tmp_path, server())
    inputs = write_inputs(tmp_path)
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, *input_flags(inputs))

    assert process.returncode == 0, process.stderr
    assert sorted(path.name for path in output.iterdir()) == [
        "choice.jsonl", "code.jsonl", "math.jsonl", "review.jsonl"]

    math = read_results(output / "math.jsonl")
    assert [result["input"] for result in math] == MATH_ROWS, "rows keep their input order"
    assert all(result["result"]["passed"] for result in math)
    assert math[0]["output"] == {"solution": "Working it out.\n#### 1"}


def test_letter_extraction_judges_multiple_choice(tmp_path, server):
    config = write_config(tmp_path, server())
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, *input_flags(write_inputs(tmp_path)))

    assert process.returncode == 0, process.stderr
    passed, failed = read_results(output / "choice.jsonl")
    assert passed["result"] == {"passed": True, "extracted_answer": "B", "attempts": 1}
    assert failed["result"] == {"passed": False, "extracted_answer": "C", "attempts": 1}


def test_llm_judge_scores_the_response_with_a_second_call(tmp_path, server):
    config = write_config(tmp_path, server())
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, *input_flags(write_inputs(tmp_path)))

    assert process.returncode == 0, process.stderr
    good, poor = read_results(output / "review.jsonl")
    assert good["result"]["judge_score"] == 8
    assert good["result"]["passed"] is True
    assert poor["result"]["judge_score"] == 3
    assert poor["result"]["passed"] is False

    judge_meta = good["meta"]["judge_meta"]
    assert judge_meta["model"] == "gpt-4"
    assert judge_meta["finish_reason"] == "stop"
    assert judge_meta["total_tokens"] == 15
    assert judge_meta["latency_ms"] >= 0

    summary = json.loads(process.stdout)
    assert summary["tasks"]["review"]["total_api_calls"] == 4, "one generation and one judge per row"


def test_script_evaluation_uses_the_exit_code(tmp_path, server):
    config = write_config(tmp_path, server())
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, *input_flags(write_inputs(tmp_path)))

    assert process.returncode == 0, process.stderr
    passing, failing = read_results(output / "code.jsonl")
    assert passing["result"]["passed"] is True
    assert failing["result"]["passed"] is False
    assert "stdout" not in json.dumps(passing), "command output stays out of the results"


def test_summary_reports_totals_per_task(tmp_path, server):
    config = write_config(tmp_path, server())
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, *input_flags(write_inputs(tmp_path)))

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["total"] == 10
    assert summary["passed"] == 7
    assert summary["failed"] == 3
    assert summary["total_api_calls"] == 12, "10 generations plus 2 judge calls"
    assert summary["tasks"]["math"] == {"total": 4, "passed": 4, "failed": 0, "total_api_calls": 4}
    assert summary["tasks"]["choice"] == {"total": 2, "passed": 1, "failed": 1, "total_api_calls": 2}
    assert summary["throughput_rpm"] > 0


def test_input_dir_finds_a_file_per_task(tmp_path, server):
    config = write_config(tmp_path, server())
    directory = write_inputs(tmp_path)["math"].parent
    output = tmp_path / "results"
    process = run_cli("--config", config, "--input-dir", directory, "--output", output)

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["total"] == 10


def test_selected_tasks_run_alone(tmp_path, server):
    config = write_config(tmp_path, server())
    inputs = write_inputs(tmp_path, names=["math"])
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, "--task", "math",
                      *input_flags(inputs))

    assert process.returncode == 0, process.stderr
    assert [path.name for path in output.iterdir()] == ["math.jsonl"]
    summary = json.loads(process.stdout)
    assert list(summary["tasks"]) == ["math"]
    assert summary["total"] == len(MATH_ROWS)


def test_eval_model_overrides_the_judge(tmp_path, server):
    config = write_config(tmp_path, server())
    inputs = write_inputs(tmp_path, names=["review"])
    output = tmp_path / "results"
    process = run_cli("--config", config, "--output", output, "--task", "review",
                      "--eval-model", "judge-model", *input_flags(inputs))

    assert process.returncode == 0, process.stderr
    record = read_results(output / "review.jsonl")[0]
    assert record["meta"]["model"] == "gpt-4"
    assert record["meta"]["judge_meta"]["model"] == "judge-model"


def test_missing_input_for_a_selected_task_exits_with_code_1(tmp_path, server):
    config = write_config(tmp_path, server())
    inputs = write_inputs(tmp_path, names=["math"])
    process = run_cli("--config", config, "--output", tmp_path / "results", *input_flags(inputs))

    assert process.returncode == 1
    assert "no input given for task 'choice'" in process.stderr


def test_input_and_input_dir_cannot_be_combined(tmp_path, server):
    config = write_config(tmp_path, server())
    inputs = write_inputs(tmp_path)
    process = run_cli("--config", config, "--input-dir", inputs["math"].parent,
                      "--output", tmp_path / "results", *input_flags(inputs))

    assert process.returncode == 1
    assert "cannot be combined" in process.stderr


def test_output_must_be_a_directory(tmp_path, server):
    config = write_config(tmp_path, server())
    output = tmp_path / "results.jsonl"
    output.write_text("")
    process = run_cli("--config", config, "--input-dir", write_inputs(tmp_path)["math"].parent,
                      "--output", output)

    assert process.returncode == 1
    assert "must be a directory" in process.stderr

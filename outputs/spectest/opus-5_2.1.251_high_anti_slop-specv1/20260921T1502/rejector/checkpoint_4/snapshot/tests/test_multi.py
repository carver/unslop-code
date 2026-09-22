"""End to end runs of multi task configs against the mock API server."""

import json

import pytest
import yaml
from mock_server import start_mock_server

import rejector

DEFAULTS = {"model": "gpt-4", "rpm": 600, "generation": {"max_tokens": 256}}

TASKS = {
    "gsm8k": {
        "prompt": {"system": "Solve the math problem.", "user": "{question}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    },
    "mmlu": {
        "prompt": {"system": "Answer with a single letter.", "user": "{question}\n\nA) {a}\nB) {b}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
        "output_field": "choice",
    },
    "review": {
        "prompt": {"system": "You are a writing assistant.", "user": "{prompt_text}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {
                "system": "You are a quality evaluator.",
                "user": "Rate this:\n{__response__}\n\nCriteria: {criteria}\n\nScore:",
            },
            "threshold": 7,
            "extract": "first_number",
        },
        "output_field": "response",
    },
    "code_gen": {
        "prompt": {"system": "Write a Python function.", "user": "{problem}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "script",
            "command_template": 'python3 -c "{test_code}"',
            "success_exit_code": 0,
        },
        "output_field": "code",
    },
}

ROWS = {
    "gsm8k": [{"question": "What is 2 + 3?", "answer": "5"}],
    "mmlu": [{"question": "Capital of France?", "a": "London", "b": "Paris", "answer": "B"}],
    "review": [{"prompt_text": "Write a haiku.", "criteria": "clarity"}],
    "code_gen": [
        {"problem": "add two numbers", "test_code": "assert 'def add' in '''{__response__}'''"}
    ],
}


def responder(payload, call):
    """Answer each task's prompt, and score every judge request as an 8."""
    system = payload["messages"][0]["content"]
    if system.startswith("You are a quality evaluator"):
        return "8"
    if system.startswith("Answer with"):
        return "The answer is B) Paris"
    if system.startswith("Write a Python"):
        return "def add(a, b):\n    return a + b"
    if system.startswith("You are a writing"):
        return "An old silent pond"
    return "2 + 3 = 5\n#### 5"


@pytest.fixture
def api():
    url, state, shutdown = start_mock_server(responder)
    yield url, state
    shutdown()


def write_config(tmp_path, names, **defaults):
    path = tmp_path / "multi.yaml"
    document = {
        "defaults": {**DEFAULTS, **defaults},
        "tasks": {name: TASKS[name] for name in names},
    }
    path.write_text(yaml.safe_dump(document))
    return path


def write_inputs(directory, names, rows=None):
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in names:
        paths[name] = directory / f"{name}.jsonl"
        lines = (rows or ROWS)[name]
        paths[name].write_text("".join(json.dumps(row) + "\n" for row in lines))
    return paths


def invoke(capsys, argv):
    code = rejector.main(["run", *argv])
    stdout = capsys.readouterr().out
    return code, json.loads(stdout) if stdout.strip() else None


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_explicit_input_mapping_writes_one_file_per_task(tmp_path, api, capsys):
    url, _ = api
    config = write_config(tmp_path, ["gsm8k", "mmlu"], api_url=url)
    inputs = write_inputs(tmp_path / "data", ["gsm8k", "mmlu"])
    output = tmp_path / "results"

    code, summary = invoke(
        capsys,
        ["--config", str(config), "--input", f"gsm8k={inputs['gsm8k']}",
         "--input", f"mmlu={inputs['mmlu']}", "--output", str(output)],
    )

    assert code == 0
    assert records(output / "gsm8k.jsonl")[0]["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    mmlu = records(output / "mmlu.jsonl")[0]
    assert mmlu["output"] == {"choice": "The answer is B) Paris"}
    assert mmlu["result"] == {"passed": True, "extracted_answer": "B", "attempts": 1}
    assert summary["total"] == 2 and summary["passed"] == 2
    counts = {
        "total": 1, "passed": 1, "failed": 0,
        "total_solutions": 1, "avg_solutions_per_input": 1.0, "total_api_calls": 1,
    }
    assert summary["tasks"] == {"gsm8k": counts, "mmlu": counts}


def test_input_dir_mode_finds_each_task_file(tmp_path, api, capsys):
    url, _ = api
    config = write_config(tmp_path, ["gsm8k", "mmlu"], api_url=url)
    write_inputs(tmp_path / "data", ["gsm8k", "mmlu"])
    output = tmp_path / "results"

    code, summary = invoke(
        capsys,
        ["--config", str(config), "--input-dir", str(tmp_path / "data"), "--output", str(output)],
    )

    assert code == 0
    assert sorted(summary["tasks"]) == ["gsm8k", "mmlu"]
    assert (output / "gsm8k.jsonl").exists() and (output / "mmlu.jsonl").exists()


def test_selected_task_runs_alone(tmp_path, api, capsys):
    url, _ = api
    config = write_config(tmp_path, ["gsm8k", "mmlu"], api_url=url)
    inputs = write_inputs(tmp_path / "data", ["gsm8k"])
    output = tmp_path / "results"

    code, summary = invoke(
        capsys,
        ["--config", str(config), "--input", f"gsm8k={inputs['gsm8k']}",
         "--output", str(output), "--task", "gsm8k"],
    )

    assert code == 0
    assert list(summary["tasks"]) == ["gsm8k"]
    assert not (output / "mmlu.jsonl").exists()


def test_llm_judge_scores_the_response(tmp_path, api, capsys):
    url, state = api
    config = write_config(tmp_path, ["review"], api_url=url)
    inputs = write_inputs(tmp_path / "data", ["review"])
    output = tmp_path / "results"

    code, summary = invoke(
        capsys,
        ["--config", str(config), "--input", f"review={inputs['review']}", "--output", str(output)],
    )
    record = records(output / "review.jsonl")[0]

    assert code == 0
    assert record["output"] == {"response": "An old silent pond"}
    assert record["result"] == {
        "passed": True, "extracted_answer": "8", "attempts": 1, "judge_score": 8
    }
    assert record["meta"]["judge_meta"]["model"] == "gpt-4"
    assert record["meta"]["judge_meta"]["total_tokens"] == 15
    # The judge call is a second request through the same server.
    assert summary["tasks"]["review"]["total_api_calls"] == 2
    assert summary["total_api_calls"] == 2
    judge_call = state.calls[-1]
    assert "An old silent pond" in judge_call["messages"][-1]["content"]
    assert "Criteria: clarity" in judge_call["messages"][-1]["content"]


def test_eval_model_flag_retargets_judge_calls(tmp_path, api, capsys):
    url, state = api
    config = write_config(tmp_path, ["review"], api_url=url)
    inputs = write_inputs(tmp_path / "data", ["review"])
    output = tmp_path / "results"

    invoke(
        capsys,
        ["--config", str(config), "--input", f"review={inputs['review']}",
         "--output", str(output), "--eval-model", "judge-9"],
    )
    record = records(output / "review.jsonl")[0]

    assert record["meta"]["model"] == "gpt-4"
    assert record["meta"]["judge_meta"]["model"] == "judge-9"
    assert {call["model"] for call in state.calls} == {"gpt-4", "judge-9"}


def test_script_evaluation_runs_the_rendered_command(tmp_path, api, capsys):
    url, _ = api
    config = write_config(tmp_path, ["code_gen"], api_url=url)
    inputs = write_inputs(tmp_path / "data", ["code_gen"])
    output = tmp_path / "results"

    code, summary = invoke(
        capsys,
        ["--config", str(config), "--input", f"code_gen={inputs['code_gen']}",
         "--output", str(output)],
    )
    record = records(output / "code_gen.jsonl")[0]

    assert code == 0
    assert record["result"] == {"passed": True, "extracted_answer": None, "attempts": 1}
    assert summary["passed"] == 1


def test_script_evaluation_reports_a_failing_command(tmp_path, api, capsys):
    url, _ = api
    config = write_config(tmp_path, ["code_gen"], api_url=url)
    rows = {"code_gen": [{"problem": "p", "test_code": "assert 'def multiply' in '''{__response__}'''"}]}
    inputs = write_inputs(tmp_path / "data", ["code_gen"], rows)
    output = tmp_path / "results"

    _, summary = invoke(
        capsys,
        ["--config", str(config), "--input", f"code_gen={inputs['code_gen']}",
         "--output", str(output)],
    )

    assert (summary["passed"], summary["failed"]) == (0, 1)


def test_rejection_sampling_judges_every_attempt(tmp_path, capsys):
    scores = iter(["3", "9"])
    server_url, state, shutdown = start_mock_server(
        lambda payload, call: next(scores)
        if payload["messages"][0]["content"].startswith("You are a quality evaluator")
        else "An old silent pond"
    )
    tasks = {"review": {**TASKS["review"], "generation": {"scheme": "rejection", "temperature": 0.8, "n": 3}}}
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump({"defaults": {**DEFAULTS, "api_url": server_url}, "tasks": tasks}))
    inputs = write_inputs(tmp_path / "data", ["review"])
    output = tmp_path / "results"

    try:
        _, summary = invoke(
            capsys,
            ["--config", str(path), "--input", f"review={inputs['review']}", "--output", str(output)],
        )
    finally:
        shutdown()
    record = records(output / "review.jsonl")[0]

    assert record["result"] == {
        "passed": True, "extracted_answer": "9", "attempts": 2, "judge_score": 9
    }
    assert [meta["judge_meta"]["finish_reason"] for meta in record["meta"]] == ["stop", "stop"]
    # Two generations and one judge call each.
    assert summary["tasks"]["review"]["total_api_calls"] == 4


def test_rows_keep_their_input_order(tmp_path, api, capsys):
    url, _ = api
    config = write_config(tmp_path, ["gsm8k"], api_url=url)
    rows = {"gsm8k": [{"question": f"What is {index} + 0?", "answer": "5"} for index in range(12)]}
    inputs = write_inputs(tmp_path / "data", ["gsm8k"], rows)
    output = tmp_path / "results"

    invoke(
        capsys,
        ["--config", str(config), "--input", f"gsm8k={inputs['gsm8k']}", "--output", str(output)],
    )

    assert [record["input"] for record in records(output / "gsm8k.jsonl")] == rows["gsm8k"]

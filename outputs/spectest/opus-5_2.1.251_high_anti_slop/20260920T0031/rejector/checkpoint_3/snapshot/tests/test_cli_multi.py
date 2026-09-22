"""End-to-end multi-task runs of the CLI against the mock server."""

import json
import pathlib
import threading

import pytest
import yaml
from mock_server import Handler, Server, Settings

from rejector import main

CONFIG = {
    "defaults": {
        "api_url": "http://127.0.0.1:9",  # replaced by --api-url whenever a request is actually made
        "model": "gpt-4",
        "rpm": 600,
        "generation": {"scheme": "greedy", "max_tokens": 64},
    },
    "tasks": {
        "gsm8k": {
            "prompt": {"system": "Answer with ####.", "user": "{question}"},
            "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
            "output_field": "solution",
        },
        "review": {
            "prompt": {"user": "Write about {prompt_text}"},
            "evaluation": {
                "type": "llm_judge",
                # The mock answers with the last number of the prompt, so `target` is the score it gives.
                "judge_prompt": {"user": "Response: {__response__}\n\nCriteria: {criteria}\nScore {target}:"},
                "threshold": 7,
                "extract": "first_number",
            },
            "output_field": "response",
        },
        "code_gen": {
            "prompt": {"user": "{problem}"},
            "evaluation": {
                "type": "script",
                "command_template": 'bash -c "{test_code}"',
                "success_exit_code": 0,
            },
            "output_field": "code",
        },
    },
}

ROWS = {
    "gsm8k": [{"question": f"Row {index} totals {index * 2}", "answer": str(index * 2)} for index in range(1, 5)],
    "review": [
        {"prompt_text": "spring", "criteria": "imagery", "target": 8},
        {"prompt_text": "autumn", "criteria": "imagery", "target": 3},
    ],
    "code_gen": [
        {"problem": "print a marker", "test_code": "echo '{__response__}' | grep -q '####'"},
        {"problem": "print a marker", "test_code": "echo '{__response__}' | grep -q 'never there'"},
    ],
}


def read_results(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text().splitlines()]


@pytest.fixture(scope="module")
def api_url():
    Handler.settings = Settings(rpm=6000, latency=0.01, fail_rate=0.0, accuracy=1.0)
    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def workspace(tmp_path):
    """A multi-task config, a `data/` directory of inputs and an output directory path."""
    config = tmp_path / "multi.yaml"
    config.write_text(yaml.safe_dump(CONFIG, sort_keys=False))
    data = tmp_path / "data"
    data.mkdir()
    for name, rows in ROWS.items():
        (data / f"{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    return str(config), str(data), tmp_path / "results"


def test_input_dir_runs_every_task_into_its_own_file(api_url, workspace, capsys):
    config, data, output = workspace
    code = main(["run", "--config", config, "--input-dir", data, "--output", str(output), "--api-url", api_url])
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert sorted(path.name for path in output.iterdir()) == ["code_gen.jsonl", "gsm8k.jsonl", "review.jsonl"]
    assert [result["input"] for result in read_results(output / "gsm8k.jsonl")] == ROWS["gsm8k"]
    assert summary["total"] == 8
    assert summary["tasks"] == {
        "gsm8k": {"total": 4, "passed": 4, "failed": 0, "total_solutions": 4,
                  "avg_solutions_per_input": 1.0, "total_api_calls": 4},
        # One generation and one judge call per row.
        "review": {"total": 2, "passed": 1, "failed": 1, "total_solutions": 2,
                   "avg_solutions_per_input": 1.0, "total_api_calls": 4},
        "code_gen": {"total": 2, "passed": 1, "failed": 1, "total_solutions": 2,
                     "avg_solutions_per_input": 1.0, "total_api_calls": 2},
    }
    assert summary["total_api_calls"] == 10
    assert summary["throughput_rpm"] > 0


def test_llm_judge_records_the_score_and_the_judge_call(api_url, workspace):
    config, data, output = workspace
    main(["run", "--config", config, "--input-dir", data, "--output", str(output), "--api-url", api_url])

    passed, failed = read_results(output / "review.jsonl")
    assert passed["result"]["judge_score"] == 8 and passed["result"]["passed"] is True
    assert failed["result"]["judge_score"] == 3 and failed["result"]["passed"] is False
    assert passed["meta"]["judge_meta"]["finish_reason"] == "stop"
    assert passed["meta"]["judge_meta"]["model"] == "gpt-4"
    assert passed["output"]["response"].startswith("Working it out.")


def test_script_evaluation_decides_each_row(api_url, workspace):
    config, data, output = workspace
    main(["run", "--config", config, "--input-dir", data, "--output", str(output), "--api-url", api_url])

    passed, failed = read_results(output / "code_gen.jsonl")
    assert (passed["result"]["passed"], failed["result"]["passed"]) == (True, False)
    assert failed["output"]["code"].startswith("Working it out.")  # greedy keeps a failing response
    assert "judge_score" not in passed["result"]


def test_selected_tasks_run_alone_with_only_their_input(api_url, workspace, capsys):
    config, data, output = workspace
    source = f"gsm8k={data}/gsm8k.jsonl"
    code = main(
        ["run", "--config", config, "--input", source, "--output", str(output), "--task", "gsm8k", "--api-url", api_url]
    )

    assert code == 0
    assert [path.name for path in output.iterdir()] == ["gsm8k.jsonl"]
    assert list(json.loads(capsys.readouterr().out)["tasks"]) == ["gsm8k"]


def test_eval_model_overrides_the_judge_model(api_url, workspace):
    config, data, output = workspace
    main(
        ["run", "--config", config, "--input", f"review={data}/review.jsonl", "--output", str(output),
         "--task", "review", "--api-url", api_url, "--eval-model", "judge-7b"]
    )

    results = read_results(output / "review.jsonl")
    assert results[0]["meta"]["model"] == "gpt-4"
    assert results[0]["meta"]["judge_meta"]["model"] == "judge-7b"


def test_missing_input_for_a_task_fails_before_any_request(workspace, capsys):
    config, data, output = workspace
    assert main(["run", "--config", config, "--input", f"gsm8k={data}/gsm8k.jsonl", "--output", str(output)]) == 1
    assert "no --input given for task(s): review, code_gen" in capsys.readouterr().err


def test_combining_input_modes_is_rejected(workspace, capsys):
    config, data, output = workspace
    assert main(["run", "--config", config, "--input", f"gsm8k={data}/gsm8k.jsonl", "--input-dir", data,
                 "--output", str(output)]) == 1
    assert "cannot be combined" in capsys.readouterr().err

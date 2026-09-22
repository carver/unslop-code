"""End-to-end runs of the CLI against the mock server."""

import json
import pathlib
import threading

import pytest
import yaml
from mock_server import Handler, Server, Settings

from rejector import main

CONFIG = {
    "task": {
        "name": "cli_demo",
        "api_url": "http://127.0.0.1:9",  # replaced by --api-url whenever a request is actually made
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {"system": "Answer with ####.", "user": "{question}"},
        "generation": {"scheme": "greedy", "max_tokens": 64},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    }
}

# The mock answers with the last number in the prompt, so these rows are all solvable.
ROWS = [{"question": f"Row {index} totals {index * 2}", "answer": str(index * 2)} for index in range(1, 9)]


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
def paths(tmp_path):
    config = tmp_path / "task.yaml"
    config.write_text(yaml.safe_dump(CONFIG))
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in ROWS))
    return str(config), str(source), str(tmp_path / "out.jsonl")


def test_run_writes_results_and_prints_a_summary(api_url, paths, capsys):
    config, source, output = paths
    assert main(["run", "--config", config, "--input", source, "--output", output, "--api-url", api_url]) == 0

    results = read_results(output)
    assert [result["input"] for result in results] == ROWS
    assert all(result["result"] == {"passed": True, "extracted_answer": row["answer"], "attempts": 1}
               for result, row in zip(results, ROWS, strict=True))
    assert all(result["output"]["solution"].endswith(row["answer"]) for result, row in zip(results, ROWS, strict=True))

    summary = json.loads(capsys.readouterr().out)
    assert summary["total"] == summary["passed"] == summary["total_api_calls"] == len(ROWS)
    assert summary["failed"] == 0


def test_rejection_run_records_every_attempt(api_url, paths, capsys):
    config, source, output = paths
    Handler.settings.accuracy = 0.0  # every response is wrong, so all attempts are rejected
    code = main(["run", "--config", config, "--input", source, "--output", output, "--api-url", api_url,
                 "--scheme", "rejection", "--temperature", "0.8", "--n", "3"])
    Handler.settings.accuracy = 1.0

    results = read_results(output)
    assert code == 0
    assert all(result["output"] is None and len(result["meta"]) == 3 for result in results)
    assert all(result["result"]["attempts"] == 3 for result in results)
    assert json.loads(capsys.readouterr().out)["total_api_calls"] == 3 * len(ROWS)


def test_missing_prompt_field_fails_before_any_request(paths, capsys, tmp_path):
    config, _, output = paths
    source = tmp_path / "bad.jsonl"
    source.write_text('{"text": "hello"}\n')

    assert main(["run", "--config", config, "--input", str(source), "--output", output]) == 1
    assert "input row 0" in capsys.readouterr().err


def test_unreadable_config_fails(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "missing.yaml"), "--input", "x", "--output", "y"]) == 1
    assert "missing.yaml" in capsys.readouterr().err

"""End-to-end ICL and multi-solution runs of the CLI against the mock server."""

import json
import pathlib
import threading

import pytest
import yaml
from mock_server import Handler, Server, Settings

from rejector import main

SETUPS = [
    {
        "name": "chain_of_thought",
        "examples": [{"input": {"question": "What is 2+2?"}, "output": "Step by step.\n#### 4"}],
    },
    {"name": "direct", "examples": [{"input": {"question": "What is 2+2?"}, "output": "#### 4"}]},
]

CONFIG = {
    "task": {
        "name": "gsm8k_icl",
        "api_url": "http://127.0.0.1:9",  # replaced by --api-url whenever a request is actually made
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {"system": "Answer with ####.", "user": "{question}"},
        "generation": {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "icl": {"setups": SETUPS, "strategy": "round_robin"},
        "num_solutions": 2,
        "output_field": "solution",
    }
}

# The mock answers with the last number in the prompt, so these rows are all solvable.
ROWS = [{"question": f"Row {index} totals {index * 2}", "answer": str(index * 2)} for index in range(1, 5)]


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
    """A config with two inline ICL setups, its input file and an output path."""
    return _write(tmp_path, CONFIG)


def _write(tmp_path, document):
    config = tmp_path / "task.yaml"
    config.write_text(yaml.safe_dump(document, sort_keys=False))
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in ROWS))
    return str(config), str(source), str(tmp_path / "out.jsonl")


def run(paths, api_url, *extra):
    config, source, output = paths
    code = main(["run", "--config", config, "--input", source, "--output", output, "--api-url", api_url, *extra])
    return code, read_results(output)


def test_rejection_collects_several_solutions_per_row(api_url, paths, capsys):
    code, results = run(paths, api_url)
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert all(result["result"] == {"passed": 2, "failed": 0, "attempts": 2} for result in results)
    assert all(
        [entry["icl_setup"] for entry in result["output"]] == ["chain_of_thought", "direct"] for result in results
    )
    assert all(result["output"][0]["solution"].endswith(row["answer"]) for result, row in zip(results, ROWS))
    assert summary["tasks"]["gsm8k_icl"] == {
        "total": 4,
        "passed": 4,
        "failed": 0,
        "total_solutions": 8,
        "avg_solutions_per_input": 2.0,
        "total_api_calls": 8,
    }


def test_metadata_records_the_setup_and_the_verdict_of_every_attempt(api_url, paths):
    _, results = run(paths, api_url)
    entries = results[0]["meta"]

    assert [entry["icl_setup"] for entry in entries] == ["chain_of_thought", "direct"]
    assert [entry["evaluation_passed"] for entry in entries] == [True, True]
    assert entries[0]["finish_reason"] == "stop"


def test_the_demonstrations_are_sent_before_the_question(api_url, tmp_path):
    """The mock echoes the last number of the prompt, so the row's own question must come last."""
    document = json.loads(json.dumps(CONFIG))
    document["task"]["icl"]["setups"][0]["examples"][0]["input"]["question"] = "What is 999999?"
    _, results = run(_write(tmp_path, document), api_url)

    assert all(not result["output"][0]["solution"].endswith("999999") for result in results)


def test_cli_flags_override_the_configured_solutions_and_strategy(api_url, paths, capsys):
    code, results = run(paths, api_url, "--num-solutions", "3", "--icl-strategy", "fixed")
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert all([entry["icl_setup"] for entry in result["output"]] == ["chain_of_thought"] * 3 for result in results)
    assert summary["tasks"]["gsm8k_icl"]["avg_solutions_per_input"] == 3.0


def test_rejection_gives_up_after_max_attempts(api_url, tmp_path, capsys):
    document = json.loads(json.dumps(CONFIG))
    document["task"]["generation"]["max_attempts"] = 3
    Handler.settings.accuracy = 0.0  # every response is wrong, so no attempt is ever kept
    code, results = run(_write(tmp_path, document), api_url)
    Handler.settings.accuracy = 1.0

    assert code == 0
    assert all(result["output"] == [] for result in results)
    assert all(result["result"] == {"passed": 0, "failed": 3, "attempts": 3} for result in results)
    assert json.loads(capsys.readouterr().out)["tasks"]["gsm8k_icl"]["total_solutions"] == 0


def test_greedy_produces_at_most_one_solution_per_setup(api_url, tmp_path, capsys):
    document = json.loads(json.dumps(CONFIG))
    document["task"]["generation"] = {"scheme": "greedy", "max_tokens": 64}
    document["task"]["num_solutions"] = 5
    code, results = run(_write(tmp_path, document), api_url)

    assert code == 0
    assert all(len(result["output"]) == 2 for result in results)
    assert json.loads(capsys.readouterr().out)["total_api_calls"] == 2 * len(ROWS)


def test_file_backed_setups_are_resolved_against_the_config(api_url, tmp_path):
    examples = tmp_path / "icl"
    examples.mkdir()
    (examples / "detailed.jsonl").write_text(
        json.dumps({"input": {"question": "What is 1+1?"}, "output": "One and one make two.\n#### 2"}) + "\n"
    )
    document = json.loads(json.dumps(CONFIG))
    document["task"]["icl"]["setups"] = [{"name": "detailed", "file": "icl/detailed.jsonl"}]
    document["task"]["num_solutions"] = 1

    code, results = run(_write(tmp_path, document), api_url)
    assert code == 0
    assert all(result["output"][0]["icl_setup"] == "detailed" for result in results)


def test_a_malformed_example_file_fails_before_any_request(api_url, tmp_path, capsys):
    examples = tmp_path / "icl"
    examples.mkdir()
    (examples / "broken.jsonl").write_text('{"input": {"question": "q"}, "output": "#### 2"}\n{"input": {}}\n')
    document = json.loads(json.dumps(CONFIG))
    document["task"]["icl"]["setups"] = [{"name": "broken", "file": "icl/broken.jsonl"}]

    config, source, output = _write(tmp_path, document)
    before = Handler.settings.calls
    assert main(["run", "--config", config, "--input", source, "--output", output]) == 1
    assert "broken.jsonl:2: 'output' must be a string" in capsys.readouterr().err
    assert Handler.settings.calls == before

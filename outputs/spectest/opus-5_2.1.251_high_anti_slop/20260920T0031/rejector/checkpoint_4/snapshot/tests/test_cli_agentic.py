"""End-to-end agentic and completions-mode runs of the CLI against the mock server."""

import json
import pathlib
import threading

import pytest
import yaml
from mock_server import Handler, Server, Settings

from rejector import main

TOOLS = [
    {
        "name": "echo_key",
        "description": "Repeat the key it is given",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        "handler": {"type": "echo"},
    }
]

CONFIG = {
    "task": {
        "name": "agentic_demo",
        "api_url": "http://127.0.0.1:9",  # replaced by --api-url whenever a request is actually made
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {"system": "Use the tools, then answer with ####.", "user": "{question}"},
        "generation": {"scheme": "agentic", "max_iterations": 5, "temperature": 0.0, "max_tokens": 64},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "answer",
        "tools": TOOLS,
    }
}

# The mock calls the first tool with the last number it has seen, then answers with that number.
ROWS = [{"question": f"Row {index} totals {index * 2}", "answer": str(index * 2)} for index in range(1, 4)]


def read_results(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text().splitlines()]


@pytest.fixture(scope="module")
def api_url():
    Handler.settings = Settings(rpm=6000, latency=0.02, fail_rate=0.0, accuracy=1.0)
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


def run(paths, api_url, *extra):
    config, source, output = paths
    code = main(["run", "--config", config, "--input", source, "--output", output, "--api-url", api_url, *extra])
    return code, read_results(output)


def test_agentic_run_records_its_tool_calls(api_url, paths, capsys):
    code, results = run(paths, api_url)

    assert code == 0
    assert [result["input"] for result in results] == ROWS
    for result, row in zip(results, ROWS, strict=True):
        assert result["output"]["answer"].endswith(row["answer"])
        assert result["result"]["passed"] is True
        assert result["result"]["iterations"] == 2
        echoed = json.dumps({"key": row["answer"]})
        assert result["result"]["tool_calls"] == [
            {"iteration": 1, "tool": "echo_key", "args": {"key": row["answer"]}, "result": echoed}
        ]
        assert result["meta"]["finish_reason"] == "stop"
        assert len(result["meta"]["iterations_detail"]) == 2
        assert result["meta"]["total_tokens"] == 30

    summary = json.loads(capsys.readouterr().out)
    assert summary["passed"] == len(ROWS)
    assert summary["total_api_calls"] == 2 * len(ROWS)
    assert summary["total_prompt_tokens"] == 20 * len(ROWS)


@pytest.mark.parametrize("api_type", ["chat", "completions"])
def test_a_run_that_never_answers_stops_at_the_iteration_limit(api_url, paths, capsys, api_type):
    Handler.settings.tool_calls = 99  # the mock keeps asking for tools and never answers
    code, results = run(paths, api_url, "--api-type", api_type)
    Handler.settings.tool_calls = 1
    capsys.readouterr()

    assert code == 0
    for result in results:
        assert result["output"] is None
        assert result["result"]["passed"] is False
        assert result["result"]["iterations"] == 5  # max_iterations from the config
        assert len(result["result"]["tool_calls"]) == 5
        assert result["meta"]["finish_reason"] == "max_iterations"


def test_agentic_run_in_completions_mode(api_url, paths, capsys):
    code, results = run(paths, api_url, "--api-type", "completions", "--chat-template", "llama3")

    assert code == 0
    for result, row in zip(results, ROWS, strict=True):
        assert result["result"]["iterations"] == 2
        assert result["result"]["tool_calls"][0]["args"] == {"key": row["answer"]}
        assert result["result"]["passed"] is True
    assert json.loads(capsys.readouterr().out)["total_api_calls"] == 2 * len(ROWS)


@pytest.mark.parametrize("template", ["chatml", "llama3", "mistral", "zephyr"])
def test_completions_mode_without_tools(api_url, paths, capsys, tmp_path, template):
    config = yaml.safe_load(yaml.safe_dump(CONFIG))
    config["task"]["generation"] = {"scheme": "greedy", "max_tokens": 64}
    config["task"].pop("tools")
    config["task"]["api_type"] = "completions"
    config["task"]["chat_template"] = template
    path = tmp_path / f"{template}.yaml"
    path.write_text(yaml.safe_dump(config))

    _, source, output = paths
    code = main(["run", "--config", str(path), "--input", source, "--output", output, "--api-url", api_url])
    capsys.readouterr()

    results = read_results(output)
    assert code == 0
    assert all(result["result"]["passed"] is True for result in results)
    assert all(result["result"] == {"passed": True, "extracted_answer": row["answer"], "attempts": 1}
               for result, row in zip(results, ROWS, strict=True))


def test_agentic_rows_overlap_in_flight(api_url, paths, capsys):
    Handler.settings.peak_in_flight = 0
    run(paths, api_url)
    capsys.readouterr()
    assert Handler.settings.peak_in_flight > 1


def test_num_solutions_writes_one_entry_per_loop(api_url, paths, capsys):
    code, results = run(paths, api_url, "--num-solutions", "2")
    capsys.readouterr()

    assert code == 0
    for result in results:
        assert len(result["output"]) == 2
        assert result["result"] == {"passed": 2, "failed": 0, "attempts": 2}
        assert [entry["finish_reason"] for entry in result["meta"]] == ["stop", "stop"]
        assert all(entry["evaluation_passed"] is True for entry in result["meta"])
        assert all(len(entry["iterations_detail"]) == 2 for entry in result["meta"])

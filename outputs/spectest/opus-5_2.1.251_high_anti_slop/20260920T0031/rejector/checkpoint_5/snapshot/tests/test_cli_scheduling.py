"""End-to-end runs of the flags that plan, pace, cost and resume a run."""

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
        "rate_limits": {"rpm": 600, "tpm": 50000, "max_concurrent": 4},
        "cost": {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03},
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
    return _write(tmp_path, CONFIG)


def _write(tmp_path, document):
    config = tmp_path / "task.yaml"
    config.write_text(yaml.safe_dump(document))
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in ROWS))
    return str(config), str(source), str(tmp_path / "out.jsonl")


def run(paths, api_url=None, *extra):
    config, source, output = paths
    argv = ["run", "--config", config, "--input", source, "--output", output]
    if api_url:
        argv += ["--api-url", api_url]
    return main(argv + list(extra))


def test_cost_is_reported_for_every_call(api_url, paths, capsys):
    assert run(paths, api_url) == 0
    cost = json.loads(capsys.readouterr().out)["cost"]

    # The mock bills 10 prompt and 5 completion tokens per call, eight calls in all.
    assert cost["total"] == round(8 * (0.01 * 0.01 + 0.005 * 0.03), 6)
    assert (cost["budget"], cost["budget_remaining"], cost["budget_exceeded"]) == (None, None, False)


def test_an_exhausted_budget_stops_the_run_without_failing(api_url, paths, capsys):
    assert run(paths, api_url, "--budget", "0.0005", "--max-concurrent", "1") == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["cost"]["budget_exceeded"] is True
    assert 0 < summary["total"] < len(ROWS)
    assert len(read_results(paths[2])) == summary["total"]


def test_a_dry_run_estimates_without_calling_the_api(paths, capsys):
    assert run(paths, None, "--dry-run") == 0
    estimate = json.loads(capsys.readouterr().out)

    assert estimate["total_inputs"] == len(ROWS)
    assert estimate["tasks"]["cli_demo"]["est_completion_tokens"] == len(ROWS) * 64
    assert estimate["est_total_cost"] > 0
    assert estimate["est_time_minutes"] == pytest.approx(len(ROWS) / 600, abs=0.05)
    assert not pathlib.Path(paths[2]).exists()


def test_resume_skips_the_rows_already_written(api_url, paths, capsys):
    assert run(paths, api_url, "--task", "cli_demo") == 0
    pathlib.Path(paths[2]).write_text("".join(json.dumps(row) + "\n" for row in read_results(paths[2])[:5]))
    capsys.readouterr()

    assert run(paths, api_url, "--resume") == 0
    summary = json.loads(capsys.readouterr().out)

    assert (summary["resumed_from"], summary["total"]) == (5, 3)
    assert [result["input"] for result in read_results(paths[2])] == ROWS


def test_resume_without_an_output_file_runs_everything(api_url, paths, capsys):
    assert run(paths, api_url, "--resume") == 0
    assert json.loads(capsys.readouterr().out)["total"] == len(ROWS)


def test_progress_lines_go_to_stderr(api_url, paths, capsys):
    assert run(paths, api_url, "--progress") == 0
    printed = capsys.readouterr()

    assert json.loads(printed.out)["total"] == len(ROWS)
    assert printed.err.splitlines()[-1].startswith(f"[{len(ROWS)}/{len(ROWS)}] 100% complete | ")
    assert "spent" in printed.err and "rpm" in printed.err


def test_the_limit_flags_reach_the_run(api_url, paths, capsys):
    assert run(paths, api_url, "--tpm", "40000", "--max-concurrent", "2", "--rpm", "900") == 0
    assert json.loads(capsys.readouterr().out)["total"] == len(ROWS)


def test_structured_output_is_parsed_and_validated(api_url, tmp_path, capsys):
    document = json.loads(json.dumps(CONFIG))
    document["task"].pop("evaluation")
    document["task"]["output_schema"] = {"type": "object", "required": ["answer"]}
    assert run(_write(tmp_path, document), api_url) == 0

    results = read_results(str(tmp_path / "out.jsonl"))
    assert all(result["output"] is None for result in results)
    assert all(result["result"]["schema_valid"] is False for result in results)
    assert json.loads(capsys.readouterr().out)["passed"] == 0

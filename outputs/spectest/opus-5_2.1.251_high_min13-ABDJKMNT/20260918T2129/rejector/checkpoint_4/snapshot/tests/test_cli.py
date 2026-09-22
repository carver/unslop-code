"""CLI surface: subcommand, required flags, optional overrides, exit codes."""

from __future__ import annotations

import json
import subprocess
import sys

from fake_server import FakeAPIServer, always, cycle
from conftest import ENTRY_POINT, base_config


# Spec: "The tool starts with: python rejector.py run --config <path> --input
# <path> --output <path>" plus "Exit codes: 0: success"
def test_run_subcommand_with_required_flags_succeeds(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        result = run_cli(config, rows)
    assert result.returncode == 0


# Spec: "--output <path>: JSONL output file, created or overwritten"
def test_output_file_is_created(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows)
    assert result.output_path.exists()
    assert len(result.rows) == 1


# Spec: "--output <path>: JSONL output file, created or overwritten"
def test_existing_output_file_is_overwritten(workdir, write_config, write_input, run_cli):
    stale = workdir / "results.jsonl"
    stale.write_text("stale line 1\nstale line 2\nstale line 3\n")
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows)
    assert result.returncode == 0
    assert "stale" not in result.output_path.read_text()
    assert len(result.rows) == 1


# Spec: "POST requests to {api_url}/v1/chat/completions"
def test_requests_go_to_chat_completions_path(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, rows)
        paths = api.paths
    assert paths == ["/v1/chat/completions"]


# Spec: "--api-url <string>" optional override replaces the config value
def test_api_url_override_replaces_config_value(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config("http://127.0.0.1:1/unused"))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows, "--api-url", api.url)
        call_count = len(api.requests)
    assert result.returncode == 0
    assert call_count == 1


# Spec: "--model <string>" optional override replaces the config value
def test_model_override_replaces_config_value(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows, "--model", "gpt-4o-mini")
        payloads = api.payloads
    assert payloads[0]["model"] == "gpt-4o-mini"
    assert result.rows[0]["meta"]["model"] == "gpt-4o-mini"


# Spec: "--max-tokens <int>" optional override replaces the config value
def test_max_tokens_override_replaces_config_value(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, rows, "--max-tokens", "77")
        payloads = api.payloads
    assert payloads[0]["max_tokens"] == 77


# Spec: "--scheme <greedy|sample|rejection>" and "--temperature <float>"
def test_scheme_and_temperature_overrides_replace_config_values(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows, "--scheme", "sample", "--temperature", "0.7")
        payloads = api.payloads
    assert result.returncode == 0
    assert payloads[0]["temperature"] == 0.7


# Spec: "--n <int>" optional override replaces the config value
def test_n_override_replaces_config_value(write_config, write_input, run_cli):
    with FakeAPIServer(cycle(["#### 1", "#### 2", "#### 5"])) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows, "--scheme", "rejection", "--temperature", "0.8", "--n", "3")
    assert result.rows[0]["result"]["attempts"] == 3
    assert result.rows[0]["result"]["passed"] is True


# Spec: "--rpm <int>" optional override replaces the config value
def test_rpm_override_is_accepted(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows, "--rpm", "120")
    assert result.returncode == 0


# Spec: "print one JSON summary object to stdout" - stdout holds only the summary
def test_stdout_contains_only_the_summary_object(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, rows)
    parsed = json.loads(result.stdout)
    assert parsed["total"] == 1


# Spec: "1: configuration or input error" - a missing config file is an error
def test_missing_config_file_exits_1(workdir, write_input, run_cli):
    rows = write_input([{"question": "q", "answer": "5"}])
    result = run_cli(workdir / "nope.yaml", rows)
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "1: configuration or input error" - a missing input file is an error
def test_missing_input_file_exits_1(workdir, write_config, run_cli):
    config = write_config(base_config("http://127.0.0.1:1"))
    result = run_cli(config, workdir / "nope.jsonl")
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: required flags - omitting one is a usage error, never a success exit
def test_omitting_required_flag_is_not_a_success(workdir, write_config):
    config = write_config(base_config("http://127.0.0.1:1"))
    proc = subprocess.run(
        [sys.executable, str(ENTRY_POINT), "run", "--config", str(config)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0

"""CLI surface: invocation form, required flags, overrides, exit codes."""

from __future__ import annotations

import json

from fake_api import FakeAPI, always
from conftest import base_task


# Spec: "The tool starts with:
#   python rejector.py run --config <path> --input <path> --output <path> [options]"
# Context: Deliverable.
def test_run_subcommand_with_required_flags(write_config, write_input, run_cli):
    with FakeAPI(responder=always("2 + 3 = 5\n#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert len(result.rows) == 1


# Spec: "--output <path>: JSONL output file, created or overwritten"
# Context: Deliverable / required flags.
def test_output_file_is_overwritten(write_config, write_input, run_cli, workdir):
    stale = workdir / "out.jsonl"
    stale.write_text('{"stale": true}\n{"stale": true}\n')
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert len(result.rows) == 1
    assert "stale" not in stale.read_text()


# Spec: "Exit codes: 0: success"
# Context: Deliverable.
def test_exit_code_zero_on_success(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert result.stderr == ""


# Spec: "Exit codes: 1: configuration or input error"
# Context: Deliverable; missing files are the simplest such error.
def test_exit_code_one_when_config_missing(write_input, run_cli, workdir):
    data = write_input([{"question": "q", "answer": "5"}])
    result = run_cli(workdir / "nope.yaml", data)
    assert result.returncode == 1
    assert result.stderr.strip()


def test_exit_code_one_when_input_missing(write_config, run_cli, workdir):
    config = write_config(base_task("http://localhost:1"))
    result = run_cli(config, workdir / "nope.jsonl")
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "Exit codes: 1: configuration or input error" — malformed JSONL row.
# Context: Input is "JSONL with one object per line".
def test_exit_code_one_on_malformed_input_line(write_config, run_cli, workdir):
    config = write_config(base_task("http://localhost:1"))
    data = workdir / "bad.jsonl"
    data.write_text('{"question": "q", "answer": "5"}\nnot json\n')
    result = run_cli(config, data)
    assert result.returncode == 1
    assert result.stderr.strip()


# Spec: "--api-url <string>" optional override "replaces the corresponding
# config value when provided".
# Context: Deliverable / optional overrides.
def test_api_url_override(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task("http://127.0.0.1:1"))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data, "--api-url", api.url)
        assert api.call_count == 1
    assert result.returncode == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: "--model <string>" override.
# Context: Deliverable / optional overrides; the model is echoed in the request
# body and in meta.
def test_model_override(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data, "--model", "gpt-4o-mini")
        assert api.requests[0]["model"] == "gpt-4o-mini"
    assert result.rows[0]["meta"]["model"] == "gpt-4o-mini"


# Spec: "--max-tokens <int>" override.
# Context: Deliverable / optional overrides.
def test_max_tokens_override(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, data, "--max-tokens", "64")
        assert api.requests[0]["max_tokens"] == 64


# Spec: "--temperature <float>" override.
# Context: Deliverable / optional overrides; combined with a sampling scheme
# because greedy forces temperature to 0.0.
def test_temperature_override(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, data, "--scheme", "sample", "--temperature", "0.7")
        assert api.requests[0]["temperature"] == 0.7


# Spec: "--scheme <greedy|sample|rejection>" override.
# Context: Deliverable / optional overrides.
def test_scheme_override_switches_behavior(write_config, write_input, run_cli):
    task = base_task("placeholder")
    with FakeAPI(responder=always("#### 1")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(
            config, data, "--scheme", "rejection", "--temperature", "0.8", "--n", "3"
        )
        assert api.call_count == 3
    assert result.rows[0]["result"]["attempts"] == 3


# Spec: "--n <int>" override.
# Context: Deliverable / optional overrides.
def test_n_override(write_config, write_input, run_cli):
    task = base_task("placeholder")
    task["generation"] = {"scheme": "rejection", "temperature": 0.9, "n": 5}
    with FakeAPI(responder=always("#### 1")) as api:
        task["api_url"] = api.url
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, data, "--n", "2")
        assert api.call_count == 2


# Spec: "--rpm <int>" override.
# Context: Deliverable / optional overrides; rpm drives concurrency, not the
# request body.
def test_rpm_override_is_accepted(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data, "--rpm", "120")
        assert "rpm" not in api.requests[0]
    assert result.returncode == 0


# Spec: "Exit codes: 1: configuration or input error"
# Context: Deliverable; a usage error (missing required flag) is reported as a
# configuration error rather than argparse's default code (see AMBIGUITIES T14).
def test_missing_required_flag_exits_one(write_config):
    import subprocess
    import sys

    from conftest import ENTRYPOINT

    proc = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "run"], capture_output=True, text=True
    )
    assert proc.returncode == 1


# Spec: an empty input is not forbidden (see AMBIGUITIES T16).
# Context: Output / "total: input row count".
def test_empty_input_produces_zeroed_summary(write_config, write_input, run_cli):
    with FakeAPI() as api:
        config = write_config(base_task(api.url))
        data = write_input([])
        result = run_cli(config, data)
    assert result.returncode == 0
    assert result.output_path.read_text() == ""
    summary = result.summary
    assert summary["total"] == 0
    assert summary["total_api_calls"] == 0
    assert summary["elapsed_seconds"] == 0.0
    assert summary["throughput_rpm"] == 0.0


# Spec: "print one JSON summary object to stdout"
# Context: Output; stdout must stay machine-readable.
def test_stdout_is_only_the_summary_json(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert json.loads(result.stdout.strip())

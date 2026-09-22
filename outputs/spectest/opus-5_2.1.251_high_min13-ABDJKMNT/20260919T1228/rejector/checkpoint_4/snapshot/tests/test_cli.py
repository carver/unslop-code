"""CLI surface: the `run` subcommand, required flags, overrides, exit codes."""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import PROJECT_ROOT, make_config


# Spec: "The tool starts with: python rejector.py run --config <path>
# --input <path> --output <path>" -- a well-formed invocation exits 0.
def test_run_subcommand_succeeds(server, run_cli):
    result = run_cli(make_config(server.url), [{"question": "2+3?", "answer": "42"}])
    assert result.exit_code == 0


# Spec: "--output <path>: JSONL output file, created or overwritten".
def test_output_file_is_overwritten(server, run_cli):
    rows = [{"question": "2+3?", "answer": "42"}]
    first = run_cli(make_config(server.url), rows)
    first.output_path.write_text("stale line\nsecond stale line\n")
    second = run_cli(make_config(server.url), rows)
    assert len(second.rows) == 1
    assert "stale" not in second.output_path.read_text()


# Spec: "Exit codes: 0: success".
def test_exit_code_zero_on_success(server, run_cli):
    result = run_cli(make_config(server.url), [{"question": "2+3?", "answer": "42"}])
    assert result.exit_code == 0
    assert result.stderr == ""


# Spec: "Exit codes: 1: configuration or input error" -- a config path that
# does not exist. (T11: usage/config errors all exit 1.)
def test_missing_config_file_exits_1(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "rejector.py"),
            "run",
            "--config",
            str(tmp_path / "nope.yaml"),
            "--input",
            str(tmp_path / "data.jsonl"),
            "--output",
            str(tmp_path / "out.jsonl"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert proc.stderr.strip()


# Spec: "1: configuration or input error" -- missing required flags.
# (T11: argparse's usage error is mapped to exit 1.)
def test_missing_required_flag_exits_1():
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "rejector.py"), "run"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1


# Spec: "--api-url <string>" override replaces the config value.
def test_api_url_override(servers, run_cli):
    configured, actual = servers(), servers()
    config = make_config(configured.url)
    result = run_cli(config, [{"question": "q", "answer": "42"}], "--api-url", actual.url)
    assert result.exit_code == 0
    assert actual.call_count == 1
    assert configured.call_count == 0


# Spec: "--model <string>" override replaces the config value.
def test_model_override(server, run_cli):
    result = run_cli(
        make_config(server.url), [{"question": "q", "answer": "42"}], "--model", "o3-mini"
    )
    assert server.payloads[0]["model"] == "o3-mini"
    assert result.rows[0]["meta"]["model"] == "o3-mini"


# Spec: "--max-tokens <int>" override replaces the config value.
def test_max_tokens_override(server, run_cli):
    run_cli(make_config(server.url), [{"question": "q", "answer": "42"}], "--max-tokens", "77")
    assert server.payloads[0]["max_tokens"] == 77


# Spec: "--temperature <float>" override replaces the config value.
def test_temperature_override(server, run_cli):
    config = make_config(server.url, generation={"scheme": "sample", "temperature": 0.2})
    run_cli(config, [{"question": "q", "answer": "42"}], "--temperature", "0.9")
    assert server.payloads[0]["temperature"] == 0.9


# Spec: "--scheme <greedy|sample|rejection>" override replaces the config value.
def test_scheme_override(server, run_cli):
    config = make_config(server.url, generation={"scheme": "greedy", "max_tokens": 16})
    result = run_cli(
        config,
        [{"question": "q", "answer": "0"}],
        "--scheme",
        "rejection",
        "--temperature",
        "0.7",
        "--n",
        "3",
    )
    assert result.exit_code == 0
    # rejection with n=3 against a server that never returns "0": 3 attempts.
    assert result.rows[0]["result"]["attempts"] == 3


# Spec: "--n <int>" override replaces the config value.
def test_n_override(server, run_cli):
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.7, "n": 2}
    )
    result = run_cli(config, [{"question": "q", "answer": "0"}], "--n", "4")
    assert result.rows[0]["result"]["attempts"] == 4
    assert server.call_count == 4


# Spec: "--rpm <int>" override replaces the config value (accepted and used
# as the request budget; see test_throughput for the behavioural check).
def test_rpm_override_accepted(server, run_cli):
    result = run_cli(
        make_config(server.url, rpm=60), [{"question": "q", "answer": "42"}], "--rpm", "600"
    )
    assert result.exit_code == 0


# Spec: "After processing finishes, print one JSON summary object to stdout"
# -- stdout carries exactly the summary, so it stays machine-readable.
def test_stdout_is_a_single_json_object(server, run_cli):
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "42"}])
    assert isinstance(json.loads(result.stdout.strip()), dict)

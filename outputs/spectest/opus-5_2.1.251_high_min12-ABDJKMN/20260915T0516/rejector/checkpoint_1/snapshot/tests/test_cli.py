"""CLI surface: invocation form, required flags, overrides, exit codes."""
import json
import os
import subprocess
import sys

import pytest
import yaml

from conftest import REJECTOR, make_config
from mock_api import MockAPI, always, chat_response


# Spec: "The tool starts with:
#   python rejector.py run --config <path> --input <path> --output <path> [options]"
# Context: Deliverable. The entry point is a `run` subcommand on rejector.py.
def test_run_subcommand_with_three_required_flags_succeeds(run_tool):
    with MockAPI(always("2 + 3 = 5\n#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "What is 2 + 3?", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert len(run.rows) == 1


def test_rejector_script_exists_at_repo_root():
    assert os.path.exists(REJECTOR)


# Spec: "--output <path>: JSONL output file, created or overwritten"
# Context: Required flags.
def test_output_file_is_created_when_absent(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.output_exists
    assert len(run.rows) == 1


def test_existing_output_file_is_overwritten_not_appended(run_tool, workdir):
    stale = workdir / "results.jsonl"
    stale.write_text("STALE LINE 1\nSTALE LINE 2\n")
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    text = stale.read_text()
    assert "STALE" not in text
    assert len(run.rows) == 1


# Spec: "Required flags: --config <path>, --input <path>, --output <path>"
# Context: Omitting a required flag is a usage/configuration error -> exit 1.
@pytest.mark.parametrize("drop", ["--config", "--input", "--output"])
def test_missing_required_flag_exits_1(workdir, write_files, drop):
    cfg, inp = write_files(make_config(), [{"question": "q", "answer": "5"}])
    args = {"--config": cfg, "--input": inp,
            "--output": str(workdir / "out.jsonl")}
    args.pop(drop)
    cmd = [sys.executable, REJECTOR, "run"]
    for k, v in args.items():
        cmd += [k, v]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.strip()


# Spec: "Exit codes: 0: success"
# Context: A well-formed run that reaches the summary exits 0.
def test_successful_run_exits_zero_and_prints_summary(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0
    assert isinstance(run.summary, dict)


# Spec: "Exit codes: 1: configuration or input error"
# Context: A missing config file is a configuration error.
def test_missing_config_file_exits_1(workdir, write_files):
    _, inp = write_files(make_config(), [{"question": "q", "answer": "5"}])
    proc = subprocess.run(
        [sys.executable, REJECTOR, "run", "--config", str(workdir / "nope.yaml"),
         "--input", inp, "--output", str(workdir / "out.jsonl")],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_missing_input_file_exits_1(workdir, write_files):
    cfg, _ = write_files(make_config(), [])
    proc = subprocess.run(
        [sys.executable, REJECTOR, "run", "--config", cfg,
         "--input", str(workdir / "nope.jsonl"),
         "--output", str(workdir / "out.jsonl")],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_malformed_yaml_config_exits_1(run_tool):
    run = run_tool(config_text="task: [unclosed\n  - :::\n", rows=[])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_malformed_jsonl_input_line_exits_1(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), [],
                       input_text='{"question": "q", "answer": "5"}\nNOT JSON\n')
    assert run.returncode == 1
    assert run.stderr.strip()


# Spec: "Optional overrides replace the corresponding config values when
#        provided: --api-url <string>"
# Context: Optional flags. The config's api_url is unreachable; the override
# is what must be used.
def test_api_url_override_replaces_config_value(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url="http://127.0.0.1:1"),
                       [{"question": "q", "answer": "5"}],
                       args=["--api-url", api.url])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 1


# Spec: "--model <string>"
def test_model_override_replaces_config_value(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, model="gpt-4"),
                       [{"question": "q", "answer": "5"}],
                       args=["--model", "llama-3"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["model"] == "llama-3"
    assert run.rows[0]["meta"]["model"] == "llama-3"


# Spec: "--max-tokens <int>"
def test_max_tokens_override_replaces_config_value(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, max_tokens=512),
                       [{"question": "q", "answer": "5"}],
                       args=["--max-tokens", "64"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["max_tokens"] == 64


# Spec: "--temperature <float>"
def test_temperature_override_replaces_config_value(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="sample",
                                   temperature=0.2),
                       [{"question": "q", "answer": "5"}],
                       args=["--temperature", "0.9"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["temperature"] == pytest.approx(0.9)


# Spec: "--scheme <greedy|sample|rejection>"
def test_scheme_override_replaces_config_value(run_tool):
    # Config says greedy (temperature forced to 0.0); the override makes it
    # sample, so the configured temperature 0.7 must be sent instead.
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="greedy",
                                   temperature=0.7),
                       [{"question": "q", "answer": "5"}],
                       args=["--scheme", "sample"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["temperature"] == pytest.approx(0.7)


def test_invalid_scheme_value_exits_1(run_tool):
    run = run_tool(make_config(), [{"question": "q", "answer": "5"}],
                   args=["--scheme", "beam"])
    assert run.returncode == 1
    assert run.stderr.strip()


# Spec: "--n <int>"
def test_n_override_replaces_config_value(run_tool):
    # Rejection with n=1 from config, overridden to 3; nothing ever passes, so
    # the row consumes exactly 3 attempts.
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="rejection",
                                   temperature=0.7, n=1),
                       [{"question": "q", "answer": "5"}],
                       args=["--n", "3"])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 3
    assert api.call_count == 3


# Spec: "--rpm <int>"
def test_rpm_override_is_accepted(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, rpm=60),
                       [{"question": "q", "answer": "5"}],
                       args=["--rpm", "120"])
    assert run.returncode == 0, run.stderr


# Spec: overrides "replace the corresponding config values when provided"
# Context: when NOT provided, the config value stands.
def test_config_values_used_when_no_overrides(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, model="mistral-7b",
                                   max_tokens=123),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["model"] == "mistral-7b"
    assert api.calls[0]["max_tokens"] == 123

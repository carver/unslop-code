"""CLI surface: invocation form, required flags, overrides, exit codes."""

import json
import os

import pytest

import fake_api


# ---------------------------------------------------------------------------
# Spec: "The tool starts with:
#        python rejector.py run --config <path> --input <path> --output <path>"
# Context: Deliverable.  The `run` subcommand with the three flags is the
# happy path and must exit 0.
# ---------------------------------------------------------------------------
def test_run_subcommand_with_three_required_flags_succeeds(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    assert res.output_exists


# ---------------------------------------------------------------------------
# Spec: "Required flags: --config <path>: YAML task config"
# Context: Deliverable.  Omitting a required flag is not a usable invocation.
# ---------------------------------------------------------------------------
def test_missing_config_flag_is_an_error(run_cli, write_input):
    inp = write_input([{"question": "q", "answer": "1"}])
    res = run_cli("run", "--input", inp)
    assert res.returncode != 0


# ---------------------------------------------------------------------------
# Spec: "--input <path>: JSONL input file"
# Context: Deliverable.  Required flag.
# ---------------------------------------------------------------------------
def test_missing_input_flag_is_an_error(run_cli, write_config):
    cfg = write_config()
    res = run_cli("run", "--config", cfg)
    assert res.returncode != 0


# ---------------------------------------------------------------------------
# Spec: "--output <path>: JSONL output file, created or overwritten"
# Context: Deliverable.  A pre-existing file at that path is replaced, not
# appended to.
# ---------------------------------------------------------------------------
def test_output_file_is_overwritten(run_cli, write_config, write_input, workdir):
    out = workdir / "results.jsonl"
    out.write_text("STALE LINE 1\nSTALE LINE 2\n")
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        inp = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        res = run_cli("run", "--config", cfg, "--input", inp,
                      "--output", str(out), check=0)
    text = out.read_text()
    assert "STALE" not in text
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Spec: "--output <path>: JSONL output file, created or overwritten"
# Context: Deliverable.  Created when absent.
# ---------------------------------------------------------------------------
def test_output_file_is_created_when_absent(run_cli, write_config, write_input,
                                            workdir):
    out = workdir / "nested_results.jsonl"
    assert not out.exists()
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_config({"api_url": api.url})
        inp = write_input([{"question": "q", "answer": "5"}])
        run_cli("run", "--config", cfg, "--input", inp,
                "--output", str(out), check=0)
    assert out.exists()


# ---------------------------------------------------------------------------
# Spec: "Optional overrides replace the corresponding config values when
#        provided: --api-url <string>"
# Context: Deliverable.  The config points at a dead URL; the override must
# be the one actually contacted.
# ---------------------------------------------------------------------------
def test_api_url_override_replaces_config_value(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api_url="http://127.0.0.1:1",
                       extra=["--api-url", api.url], check=0)
        assert api.call_count == 1
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "--model <string>"
# Context: Deliverable.  The override is what is sent on the wire and what is
# reported in meta.model.
# ---------------------------------------------------------------------------
def test_model_override_replaces_config_value(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, extra=["--model", "gpt-4o-mini"], check=0)
        assert api.bodies()[0]["model"] == "gpt-4o-mini"
    assert res.rows[0]["meta"]["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Spec: "--max-tokens <int>"
# Context: Deliverable.  The override appears in the request body.
# ---------------------------------------------------------------------------
def test_max_tokens_override_replaces_config_value(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, extra=["--max-tokens", "77"], check=0)
        assert api.bodies()[0]["max_tokens"] == 77


# ---------------------------------------------------------------------------
# Spec: "--temperature <float>"
# Context: Deliverable.  With a non-greedy scheme the override reaches the API
# body as a float.
# ---------------------------------------------------------------------------
def test_temperature_override_replaces_config_value(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"generation": {"scheme": "sample",
                                           "temperature": 0.3}},
                 extra=["--temperature", "0.9"], check=0)
        assert api.bodies()[0]["temperature"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Spec: "--scheme <greedy|sample|rejection>"
# Context: Deliverable.  Overriding a greedy config to `sample` must take the
# sample code path (temperature > 0 is then required and is honoured).
# ---------------------------------------------------------------------------
def test_scheme_override_replaces_config_value(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"generation": {"scheme": "greedy",
                                           "temperature": 0.7}},
                 extra=["--scheme", "sample"], check=0)
        assert api.bodies()[0]["temperature"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Spec: "--scheme <greedy|sample|rejection>"
# Context: Deliverable.  Only the three listed schemes are accepted.
# ---------------------------------------------------------------------------
def test_unknown_scheme_on_cli_is_rejected(run_task):
    res = run_task(extra=["--scheme", "beam"])
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "--n <int>"
# Context: Deliverable.  For rejection the override bounds the attempt count.
# ---------------------------------------------------------------------------
def test_n_override_replaces_config_value(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 999")) as api:
        res = run_task(api,
                       task={"generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 2}},
                       extra=["--n", "4"], check=0)
        assert api.call_count == 4
    assert res.rows[0]["result"]["attempts"] == 4


# ---------------------------------------------------------------------------
# Spec: "--rpm <int>"
# Context: Deliverable.  Accepted as an integer override; the run still works.
# ---------------------------------------------------------------------------
def test_rpm_override_is_accepted(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, extra=["--rpm", "120"], check=0)
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "Exit codes: 0: success"
# Context: Deliverable.  A clean run exits 0 with a summary on stdout and
# nothing fatal on stderr.
# ---------------------------------------------------------------------------
def test_successful_run_exits_zero(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, check=0)
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "Exit codes: 1: configuration or input error"
# Context: Deliverable.  A missing config file is a configuration error.
# ---------------------------------------------------------------------------
def test_missing_config_file_exits_one(run_cli, write_input):
    inp = write_input([{"question": "q", "answer": "1"}])
    res = run_cli("run", "--config", "does_not_exist.yaml", "--input", inp)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "Exit codes: 1: configuration or input error"
# Context: Deliverable.  A missing input file is an input error.
# ---------------------------------------------------------------------------
def test_missing_input_file_exits_one(run_cli, write_config):
    cfg = write_config()
    res = run_cli("run", "--config", cfg, "--input", "nope.jsonl")
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "Exit codes: 1: configuration or input error"
# Context: Deliverable.  Unparseable YAML is a configuration error.
# ---------------------------------------------------------------------------
def test_malformed_yaml_exits_one(run_task):
    res = run_task(config_raw="task: [unclosed\n  : :\n")
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "Exit codes: 1: configuration or input error"
# Context: Input.  "The input file is JSONL with one object per line" — a line
# that is not JSON is an input error (see AMBIGUITIES T17).
# ---------------------------------------------------------------------------
def test_malformed_jsonl_line_exits_one(run_task):
    res = run_task(input_raw='{"question": "a", "answer": "1"}\nnot json\n')
    assert res.returncode == 1
    assert res.stderr.strip()

"""Spec section: Deliverable (CLI surface, flags, overrides, exit codes)."""
from __future__ import annotations

import json

from conftest import base_config
from mock_server import MockAPI, always, completion


# ---------------------------------------------------------------------------
# Phrase: "The tool starts with:
#   python rejector.py run --config <path> --input <path> --output <path>"
# Context: Deliverable.  The `run` subcommand plus the three required flags is
# the canonical invocation and must succeed on a well-formed task.
# ---------------------------------------------------------------------------
def test_run_subcommand_with_required_flags_succeeds(run_tool, write_config,
                                                     write_input):
    with MockAPI(always("2 + 3 = 5\n#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Phrase: "--output <path>: JSONL output file, created or overwritten"
# Context: Deliverable / Required flags.
# ---------------------------------------------------------------------------
def test_output_file_is_created(run_tool, write_config, write_input, workdir):
    out = str(workdir / "fresh" / "results.jsonl")
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, output=out)
    assert res.returncode == 0, res
    assert res.output_exists


def test_output_file_is_overwritten(run_tool, write_config, write_input,
                                    workdir):
    out = workdir / "results.jsonl"
    out.write_text("STALE LINE 1\nSTALE LINE 2\nSTALE LINE 3\n")
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, output=str(out))
    assert res.returncode == 0, res
    assert "STALE" not in out.read_text()
    assert len(res.rows) == 1


# ---------------------------------------------------------------------------
# Phrase: "Optional overrides replace the corresponding config values when
#          provided: --api-url <string>"
# Context: Deliverable.  The config points at a dead port; the override must win.
# ---------------------------------------------------------------------------
def test_api_url_override_replaces_config_value(run_tool, write_config,
                                                write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config("http://127.0.0.1:1"))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--api-url", api.url])
        assert api.call_count == 1
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "--model <string>"
# Context: Deliverable / optional overrides.  Affects both the request body and
# the emitted `meta.model`.
# ---------------------------------------------------------------------------
def test_model_override(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--model", "llama-3"])
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["model"] == "llama-3"
    assert res.rows[0]["meta"]["model"] == "llama-3"


# ---------------------------------------------------------------------------
# Phrase: "--max-tokens <int>"
# Context: Deliverable / optional overrides.
# ---------------------------------------------------------------------------
def test_max_tokens_override(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--max-tokens", "64"])
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["max_tokens"] == 64


# ---------------------------------------------------------------------------
# Phrase: "--scheme <greedy|sample|rejection>" and "--temperature <float>"
# Context: Deliverable / optional overrides.  Switching a greedy config to
# `sample` via the CLI must also carry the overridden temperature.
# ---------------------------------------------------------------------------
def test_scheme_and_temperature_override(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data,
                       extra=["--scheme", "sample", "--temperature", "0.7"])
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["temperature"] == 0.7


# ---------------------------------------------------------------------------
# Phrase: "--n <int>"
# Context: Deliverable / optional overrides.  Under rejection, `n` bounds the
# attempt count, so the override is observable as the number of API calls.
# ---------------------------------------------------------------------------
def test_n_override(run_tool, write_config, write_input):
    cfg_dict = base_config(None,
                           generation={"scheme": "rejection",
                                       "temperature": 0.8, "n": 2})
    with MockAPI(always("no answer here")) as api:
        cfg_dict["task"]["api_url"] = api.url
        cfg = write_config(cfg_dict)
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--n", "4"])
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 4
    assert res.rows[0]["result"]["attempts"] == 4


# ---------------------------------------------------------------------------
# Phrase: "--rpm <int>"
# Context: Deliverable / optional overrides.  Accepted and does not break a run.
# ---------------------------------------------------------------------------
def test_rpm_override_accepted(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--rpm", "120"])
    assert res.returncode == 0, res


# ---------------------------------------------------------------------------
# Phrase: "Exit codes: 0: success"
# Context: Deliverable.  A run where rows merely fail evaluation is still a
# successful run.
# ---------------------------------------------------------------------------
def test_exit_zero_even_when_rows_fail_evaluation(run_tool, write_config,
                                                  write_input):
    with MockAPI(always("#### 7")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Phrase: "Exit codes: 1: configuration or input error"
# Context: Deliverable.  A missing config file is a configuration error.
# ---------------------------------------------------------------------------
def test_missing_config_file_exits_1(run_tool, write_input, workdir):
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(str(workdir / "nope.yaml"), data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a missing input file is an input error.
def test_missing_input_file_exits_1(run_tool, write_config, workdir):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    res = run_tool(cfg, str(workdir / "nope.jsonl"))
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - malformed JSON on an input line is an input error.
def test_malformed_input_line_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input('{"question": "ok", "answer": "5"}\nnot json at all\n')
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - unparseable YAML is a configuration error.
def test_malformed_yaml_exits_1(run_tool, write_input, workdir):
    cfg = workdir / "bad.yaml"
    cfg.write_text("task: [unclosed\n")
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(str(cfg), data)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase (ambiguity T19): "Exit codes: 0: success / 1: configuration or input
#          error" - only these two codes are documented, so a usage error
#          (missing required flag, missing subcommand) also exits 1.
# Context: Deliverable.
# ---------------------------------------------------------------------------
def test_missing_required_flag_exits_1(run_tool, write_input, workdir):
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(config=None, input=data)
    assert res.returncode == 1
    assert res.stderr.strip()


def test_missing_subcommand_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data, subcommand=None)
    assert res.returncode == 1
    assert res.stderr.strip()


def test_unknown_subcommand_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data, subcommand="walk")
    assert res.returncode == 1
    assert res.stderr.strip()

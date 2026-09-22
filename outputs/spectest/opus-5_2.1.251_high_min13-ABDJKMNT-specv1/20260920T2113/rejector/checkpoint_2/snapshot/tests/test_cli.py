"""The deliverable's command line surface and exit codes."""

from __future__ import annotations

import json

from tests.conftest import task_config
from tests.fake_api import ok


ROW = {"question": "What is 2 + 3?", "answer": "5"}


# "The tool starts with: python rejector.py run --config <path> --input <path>
#  --output <path>"
# "Exit codes: 0: success"
def test_run_succeeds_and_writes_output(cli, static_api):
    server = static_api("2 + 3 = 5\n#### 5")
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert len(run.rows) == 1


# "--output <path>: JSONL output file, created or overwritten"
def test_existing_output_is_overwritten(cli, static_api):
    server = static_api("2 + 3 = 5\n#### 5")
    stale = cli.tmp_path / "results.jsonl"
    stale.write_text("stale line\n" * 5)
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert "stale" not in stale.read_text()
    assert len(run.rows) == 1


# "--api-url <string>" override is used instead of the config value
def test_api_url_override(cli, static_api):
    server = static_api("#### 5")
    config = task_config(api_url="http://127.0.0.1:1/unreachable")
    run = cli.run(config, [ROW], "--api-url", server.url)
    assert run.returncode == 0
    assert len(server.log.calls) == 1


# "--model <string>" / "--max-tokens <int>" reach the request body
def test_model_and_max_tokens_overrides(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [ROW], "--model", "gpt-5", "--max-tokens", "64")
    assert run.returncode == 0
    body = server.log.bodies[0]
    assert body["model"] == "gpt-5"
    assert body["max_tokens"] == 64
    assert run.rows[0]["meta"]["model"] == "gpt-5"


# "--scheme <greedy|sample|rejection>" / "--temperature <float>"
def test_scheme_and_temperature_overrides(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(
        task_config(api_url=server.url), [ROW],
        "--scheme", "sample", "--temperature", "0.7",
    )
    assert run.returncode == 0
    assert server.log.bodies[0]["temperature"] == 0.7


# "--n <int>" override drives the rejection attempt budget
def test_n_override(cli, api):
    server = api(lambda index, body: ok("#### 0"))
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 2},
    )
    run = cli.run(config, [ROW], "--n", "4")
    assert run.returncode == 0
    assert run.rows[0]["result"]["attempts"] == 4


# "--rpm <int>" override is accepted
def test_rpm_override(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [ROW], "--rpm", "120")
    assert run.returncode == 0


# "Exit codes: 1: configuration or input error"
def test_invalid_config_exits_one(cli, static_api):
    server = static_api("#### 5")
    config = task_config(api_url=server.url, generation={"scheme": "sample", "temperature": 0.0})
    run = cli.run(config, [ROW])
    assert run.returncode == 1
    assert "temperature" in run.stderr
    assert not run.output_path.exists()


# "Exit codes: 1: configuration or input error" (missing input file)
def test_missing_input_file_exits_one(cli, static_api):
    server = static_api("#### 5")
    config_path = cli.write_config(task_config(api_url=server.url))
    import subprocess, sys
    from tests.conftest import ENTRYPOINT, REPO_ROOT
    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "run",
         "--config", str(config_path),
         "--input", str(cli.tmp_path / "missing.jsonl"),
         "--output", str(cli.tmp_path / "out.jsonl")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 1
    assert completed.stderr.strip()


# "Exit codes: 1: configuration or input error" (T18: a line that is not a
# JSON object is an input error; blank lines are skipped)
def test_malformed_input_line_exits_one(cli, static_api):
    server = static_api("#### 5")
    rows = json.dumps(ROW) + "\nnot json\n"
    run = cli.run(task_config(api_url=server.url), rows)
    assert run.returncode == 1
    assert run.stderr.strip()


def test_blank_input_lines_are_skipped(cli, static_api):
    server = static_api("#### 5")
    rows = json.dumps(ROW) + "\n\n" + json.dumps(ROW) + "\n\n"
    run = cli.run(task_config(api_url=server.url), rows)
    assert run.returncode == 0
    assert run.summary["total"] == 2
    assert len(run.rows) == 2


# "If a prompt template references {question} and row 0 is {"text": "hello"},
#  exit with code 1 and print an error to stderr naming row 0 and missing field
#  question"
def test_missing_prompt_field_exits_one_naming_row_and_field(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [{"text": "hello"}])
    assert run.returncode == 1
    assert "0" in run.stderr and "question" in run.stderr
    assert run.stdout.strip() == ""
    assert len(server.log.calls) == 0


# "Every row must contain all fields referenced by the prompt templates" /
# "each row must also contain that field" (answer_field)
def test_missing_answer_field_exits_one(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [{"question": "2+3"}])
    assert run.returncode == 1
    assert "answer" in run.stderr


# "python rejector.py run ..." - the run subcommand is required
def test_missing_subcommand_is_an_error(cli):
    import subprocess, sys
    from tests.conftest import ENTRYPOINT, REPO_ROOT
    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT)], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode != 0

"""`script` evaluation: rendered shell command, exit codes, and timeouts."""

from __future__ import annotations

import json

import pytest

from tests.conftest import SPEC_ROWS, multi_config, task_config
from tests.fake_api import ok

#: The spec's script-evaluation example row: `test_code` itself holds `{__response__}`.
SHELL_ROW = {
    "problem": "write good code",
    "test_code": "echo '{__response__}' | grep -q 'good code'",
}


def script_task(server, command_template: str, **evaluation) -> dict:
    """A single-task config whose evaluation runs `command_template`."""
    config = task_config(api_url=server.url)
    config["task"]["prompt"] = {"user": "{problem}"}
    config["task"]["output_field"] = "code"
    config["task"]["evaluation"] = {
        "type": "script",
        "command_template": command_template,
        **evaluation,
    }
    return config


# "`command_template` may reference row fields and `__response__`"
def test_command_template_uses_row_fields_and_response(cli, static_api):
    server = static_api("blue")
    config = script_task(server, 'test "{__response__}" = "{expected}"')
    run = cli.run(config, [{"problem": "colour", "expected": "blue"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


# "`command_template` may reference row fields and `__response__`"
# (a mismatch fails the row)
def test_command_template_failure_fails_the_row(cli, static_api):
    server = static_api("red")
    config = script_task(server, 'test "{__response__}" = "{expected}"')
    run = cli.run(config, [{"problem": "colour", "expected": "blue"}])
    assert run.rows[0]["result"]["passed"] is False
    assert run.summary["failed"] == 1


# "if a row field such as `{test_code}` expands to text that itself contains
#  `{__response__}`, substitute `__response__` before executing the command"
def test_response_nested_inside_a_row_field_is_substituted(cli, static_api):
    server = static_api("this is good code")
    config = script_task(server, "{test_code}")
    run = cli.run(config, [SHELL_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


# "then the rendered shell command uses the generated response text in place of
#  `__response__`. A zero exit code passes; non-zero fails."
def test_nested_response_that_does_not_match_fails(cli, static_api):
    server = static_api("this is bad prose")
    config = script_task(server, "{test_code}")
    run = cli.run(config, [SHELL_ROW])
    assert run.rows[0]["result"]["passed"] is False


# "run the rendered command in a shell"
def test_command_runs_through_a_shell(cli, static_api):
    server = static_api("needle")
    config = script_task(server, "echo '{__response__}' | grep -q needle && true")
    run = cli.run(config, [{"problem": "find it"}])
    assert run.rows[0]["result"]["passed"] is True


# "exit code equal to `success_exit_code` means pass; any other exit code means fail"
@pytest.mark.parametrize("exit_code,passed", [(0, True), (1, False), (7, False)])
def test_exit_code_decides_the_verdict(cli, static_api, exit_code, passed):
    server = static_api("x")
    config = script_task(server, f"exit {exit_code}")
    run = cli.run(config, [{"problem": "p"}])
    assert run.rows[0]["result"]["passed"] is passed


# "exit code equal to `success_exit_code` means pass"
# (a non-zero `success_exit_code` inverts which codes pass)
@pytest.mark.parametrize("exit_code,passed", [(3, True), (0, False)])
def test_custom_success_exit_code(cli, static_api, exit_code, passed):
    server = static_api("x")
    config = script_task(server, f"exit {exit_code}", success_exit_code=3)
    run = cli.run(config, [{"problem": "p"}])
    assert run.rows[0]["result"]["passed"] is passed


# "capture command stdout and stderr, but do not include them in the JSONL output"
def test_command_output_is_not_written_to_the_jsonl(cli, static_api):
    server = static_api("x")
    config = script_task(server, "echo SENTINEL_OUT; echo SENTINEL_ERR >&2")
    run = cli.run(config, [{"problem": "p"}])
    text = run.output_path.read_text()
    assert "SENTINEL_OUT" not in text and "SENTINEL_ERR" not in text
    assert set(json.loads(text.splitlines()[0])) == {"input", "output", "result", "meta"}


# "command timeout is 10 seconds; timeout is a failed evaluation"
def test_timeout_fails_the_evaluation(cli, static_api):
    server = static_api("x")
    config = script_task(server, "sleep 30")
    run = cli.run(config, [{"problem": "p"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


# "script" evaluation drives rejection sampling like any other evaluation
def test_script_evaluation_drives_rejection(cli, api):
    server = api(lambda index, body: ok("no" if index < 2 else "yes"))
    config = script_task(server, 'test "{__response__}" = yes')
    config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.8, "n": 4}
    run = cli.run(config, [{"problem": "p"}])
    assert run.rows[0]["result"]["attempts"] == 3
    assert run.rows[0]["result"]["passed"] is True
    assert run.rows[0]["output"] == {"code": "yes"}


# "evaluation: type: script" is accepted inside a multi-task config
def test_script_task_in_a_multi_task_config(cli, static_api):
    server = static_api("this is good code")
    config = multi_config("code_gen", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"code_gen": [SPEC_ROWS["code_gen"]]})
    assert run.returncode == 0, run.stderr
    assert run.task_rows("code_gen")[0]["result"]["passed"] is True

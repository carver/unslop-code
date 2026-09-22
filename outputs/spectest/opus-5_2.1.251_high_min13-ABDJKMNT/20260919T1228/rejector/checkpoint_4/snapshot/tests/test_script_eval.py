"""`script` evaluation: rendered shell commands judged by their exit code."""

from __future__ import annotations

import time

from conftest import exact_match_task, make_config, make_multi_config

ROW = [{"problem": "write good code"}]


def script_config(server_url, command, **evaluation):
    """A greedy task whose evaluation runs `command` against each response."""
    evaluation = {"type": "script", "command_template": command, **evaluation}
    return make_config(
        server_url,
        prompt={"system": "Write code.", "user": "{problem}"},
        evaluation=evaluation,
        output_field="code",
    )


# Spec: "exit code equal to `success_exit_code` means pass".
def test_zero_exit_code_passes(servers, run_cli):
    server = servers(contents=["hello"])
    config = script_config(server.url, "test '{__response__}' = 'hello'")
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["result"]["passed"] is True


# Spec: "any other exit code means fail".
def test_non_zero_exit_code_fails(servers, run_cli):
    server = servers(contents=["goodbye"])
    config = script_config(server.url, "test '{__response__}' = 'hello'")
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert row["result"]["passed"] is False
    assert row["output"] == {"code": "goodbye"}


# Spec: "exit code equal to `success_exit_code` means pass" -- with a
# success code other than zero.
def test_custom_success_exit_code(servers, run_cli):
    server = servers(contents=["anything"])
    config = script_config(server.url, "exit 7", success_exit_code=7)
    result = run_cli(config, ROW)
    assert result.rows[0]["result"]["passed"] is True


# Spec: "any other exit code means fail" -- including zero when a non-zero
# code is the configured success.
def test_zero_exit_fails_when_success_code_is_not_zero(servers, run_cli):
    server = servers(contents=["anything"])
    config = script_config(server.url, "true", success_exit_code=3)
    result = run_cli(config, ROW)
    assert result.rows[0]["result"]["passed"] is False


# Spec: "`command_template` may reference row fields and `__response__`".
def test_command_template_uses_row_fields(servers, run_cli):
    server = servers(contents=["a solution"])
    config = script_config(server.url, "test '{expected}' = '{__response__}'")
    result = run_cli(config, [{"problem": "p", "expected": "a solution"}])
    assert result.rows[0]["result"]["passed"] is True


# Spec: "if a row field such as `{test_code}` expands to text that itself
# contains `{__response__}`, substitute `__response__` before executing" --
# the spec's own example row.
def test_nested_response_placeholder_is_substituted(servers, run_cli):
    server = servers(contents=["this is good code"])
    config = script_config(server.url, 'python3 -c "print()" ; {test_code}')
    rows = [
        {
            "problem": "write good code",
            "test_code": "echo '{__response__}' | grep -q 'good code'",
        }
    ]
    result = run_cli(config, rows)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["result"]["passed"] is True


# Spec: "run the rendered command in a shell" -- pipes and redirection work.
def test_command_runs_in_a_shell(servers, run_cli):
    server = servers(contents=["needle in haystack"])
    config = script_config(server.url, "echo '{__response__}' | grep -q needle")
    result = run_cli(config, ROW)
    assert result.rows[0]["result"]["passed"] is True


# Spec: "capture command stdout and stderr, but do not include them in the
# JSONL output".
def test_command_output_is_not_written_to_the_jsonl(servers, run_cli):
    server = servers(contents=["hello"])
    config = script_config(
        server.url, "echo MARKER_STDOUT; echo MARKER_STDERR 1>&2; true"
    )
    result = run_cli(config, ROW)
    text = result.output_path.read_text()
    assert "MARKER_STDOUT" not in text
    assert "MARKER_STDERR" not in text


# Spec: "command timeout is 10 seconds; timeout is a failed evaluation".
def test_timeout_fails_the_row(servers, run_cli):
    server = servers(contents=["hello"])
    config = script_config(server.url, "sleep 30")
    started = time.monotonic()
    result = run_cli(config, ROW, timeout=60)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["result"]["passed"] is False
    assert time.monotonic() - started < 30


# Spec: script evaluation extracts nothing from the response. (T22)
def test_script_reports_no_extracted_answer(servers, run_cli):
    server = servers(contents=["hello"])
    config = script_config(server.url, "true")
    result = run_cli(config, ROW)
    assert result.rows[0]["result"] == {
        "passed": True,
        "extracted_answer": None,
        "attempts": 1,
    }


# Spec: script evaluation drives rejection sampling like any other evaluation.
def test_rejection_resamples_until_the_script_passes(servers, run_cli):
    server = servers(contents=["bad", "bad", "good"], workers=1)
    config = script_config(server.url, "test '{__response__}' = 'good'")
    config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3}
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"code": "good"}


# Spec: the `code_gen` task of the multi-task example, run alongside another
# task.
def test_script_task_in_a_multi_task_config(servers, run_multi):
    server = servers(contents=["#### 42"])
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(),
            "code_gen": {
                "prompt": {"system": "Write code.", "user": "{problem}"},
                "generation": {"scheme": "greedy"},
                "evaluation": {
                    "type": "script",
                    "command_template": "echo '{__response__}' | grep -q 42",
                    "success_exit_code": 0,
                },
                "output_field": "code",
            },
        },
    )
    result = run_multi(
        config, {"gsm8k": [{"question": "q", "answer": "42"}], "code_gen": ROW}
    )
    assert result.exit_code == 0, result.stderr
    assert result.rows("code_gen")[0]["result"]["passed"] is True

"""`script` evaluation: rendered shell commands judged by exit code."""

from __future__ import annotations

import pytest
from fake_server import FakeAPIServer, Reply, always, completion
from conftest import multi_config

CODE_TASK = {
    "prompt": {"system": "Write a Python function.", "user": "{problem}"},
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "script", "command_template": "python3 -c \"{test_code}\"", "success_exit_code": 0},
    "output_field": "code",
}


def _run(write_config, write_input, run_argv, evaluation, content, rows, *extra):
    """Run a one-task script config and return the CLI result."""
    task = dict(CODE_TASK, evaluation=evaluation)
    with FakeAPIServer(always(content)) as api:
        config = write_config(multi_config(api.url, {"code_gen": task}))
        inputs = write_input(rows, name="code_gen.jsonl")
        return run_argv("--config", config, "--input", f"code_gen={inputs}", *extra)


# Spec: "command_template may reference row fields and __response__" plus
# "exit code equal to success_exit_code means pass"
def test_zero_exit_code_passes(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "test '{__response__}' = '{expected}'"},
        "good code",
        [{"problem": "p", "expected": "good code"}],
    )
    assert result.returncode == 0
    assert result.task_rows("code_gen")[0]["result"]["passed"] is True


# Spec: "any other exit code means fail"
def test_non_zero_exit_code_fails(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "test '{__response__}' = '{expected}'"},
        "bad code",
        [{"problem": "p", "expected": "good code"}],
    )
    assert result.task_rows("code_gen")[0]["result"]["passed"] is False


# Spec: "If the row contains {"problem": ..., "test_code": "echo
# '{__response__}' | grep -q 'good code'"} then the rendered shell command uses
# the generated response text in place of __response__"
def test_response_nested_inside_a_row_field_is_substituted(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "{test_code}", "success_exit_code": 0},
        "this is good code",
        [{"problem": "write good code", "test_code": "echo '{__response__}' | grep -q 'good code'"}],
    )
    assert result.task_rows("code_gen")[0]["result"]["passed"] is True


# Spec: same nested case, where the response does not satisfy the test
def test_response_nested_inside_a_row_field_can_fail(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "{test_code}", "success_exit_code": 0},
        "this is bad code",
        [{"problem": "write good code", "test_code": "echo '{__response__}' | grep -q 'good code'"}],
    )
    assert result.task_rows("code_gen")[0]["result"]["passed"] is False


# Spec: "run the rendered command in a shell" - shell syntax such as pipes and
# quoting is interpreted
def test_command_runs_through_a_shell(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "echo '{__response__}' | grep -q code && true"},
        "some code",
        [{"problem": "p"}],
    )
    assert result.task_rows("code_gen")[0]["result"]["passed"] is True


# Spec: "exit code equal to success_exit_code means pass" - a non-zero success
# code inverts the usual convention
def test_custom_success_exit_code(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "exit 3", "success_exit_code": 3},
        "whatever",
        [{"problem": "p"}],
    )
    assert result.task_rows("code_gen")[0]["result"]["passed"] is True


# Spec: "exit code equal to success_exit_code means pass; any other exit code
# means fail"
def test_zero_exit_fails_when_success_code_is_not_zero(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "true", "success_exit_code": 3},
        "whatever",
        [{"problem": "p"}],
    )
    assert result.task_rows("code_gen")[0]["result"]["passed"] is False


# Spec: "capture command stdout and stderr, but do not include them in the
# JSONL output"
def test_command_output_is_absent_from_the_jsonl(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "echo NOISE_OUT; echo NOISE_ERR 1>&2"},
        "whatever",
        [{"problem": "p"}],
    )
    text = (result.output_path / "code_gen.jsonl").read_text()
    assert "NOISE_OUT" not in text
    assert "NOISE_ERR" not in text
    assert "NOISE_OUT" not in result.stdout


# Spec: "command timeout is 10 seconds; timeout is a failed evaluation"
@pytest.mark.slow
def test_timeout_is_a_failed_evaluation(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "sleep 30"},
        "whatever",
        [{"problem": "p"}],
    )
    assert result.returncode == 0
    assert result.task_rows("code_gen")[0]["result"]["passed"] is False


# Spec: script evaluation drives the rejection scheme like any other
# evaluation ("stop at the first response that passes evaluation")
def test_script_evaluation_drives_rejection(write_config, write_input, run_argv):
    contents = ["bad code", "bad code", "good code"]

    def responder(payload, index):
        return Reply(completion(contents[min(index, len(contents) - 1)]))

    task = dict(
        CODE_TASK,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 3},
        evaluation={"type": "script", "command_template": "echo '{__response__}' | grep -q good"},
    )
    with FakeAPIServer(responder) as api:
        config = write_config(multi_config(api.url, {"code_gen": task}))
        inputs = write_input([{"problem": "p"}], name="code_gen.jsonl")
        result = run_argv("--config", config, "--input", f"code_gen={inputs}")

    row = result.task_rows("code_gen")[0]
    assert row["result"]["attempts"] == 3
    assert row["result"]["passed"] is True


# Spec: "command_template may reference row fields" - referenced fields are
# required of every input row
def test_missing_command_template_field_exits_1(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "command_template": "test -n '{expected}'"},
        "whatever",
        [{"problem": "p"}],
    )
    assert result.returncode == 1
    assert "expected" in result.stderr


# Spec: the script evaluation type needs a command to run
def test_script_without_command_template_exits_1(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv,
        {"type": "script", "success_exit_code": 0},
        "whatever",
        [{"problem": "p"}],
    )
    assert result.returncode == 1
    assert "command_template" in result.stderr

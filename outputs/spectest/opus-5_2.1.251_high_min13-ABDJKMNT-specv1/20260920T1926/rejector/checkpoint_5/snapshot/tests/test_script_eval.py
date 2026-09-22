"""`script` evaluation: command rendering, exit codes, capture and timeout."""

from __future__ import annotations

import asyncio

import pytest

from conftest import base_defaults, script_task, task_rows
from fake_api import FakeAPI, Reply, always, by_question, sequence

from taskrunner.config import ConfigError, ScriptConfig, build_run_config
from taskrunner.script_eval import render_command, run_script


def script(command_template: str, success_exit_code: int = 0) -> ScriptConfig:
    return ScriptConfig(command_template=command_template, success_exit_code=success_exit_code)


def run(config: ScriptConfig, row: dict, response: str) -> bool:
    return asyncio.run(run_script(config, row, response))


# Spec: "`command_template` may reference row fields and `__response__`"
# Context: Evaluation Additions / `script` evaluation / Rules.
def test_command_template_renders_row_fields_and_response():
    command = render_command("echo {name} {__response__}", {"name": "bob"}, "hi")
    assert command == "echo bob hi"


# Spec: "if a row field such as `{test_code}` expands to text that itself
# contains `{__response__}`, substitute `__response__` before executing the
# command"
# Context: Evaluation Additions / `script` evaluation / Rules.
def test_response_inside_an_expanded_row_field_is_substituted():
    row = {"test_code": "echo '{__response__}' | grep -q 'good code'"}
    command = render_command('bash -c "{test_code}"', row, "this is good code")
    assert command == "bash -c \"echo 'this is good code' | grep -q 'good code'\""


# Spec: "run the rendered command in a shell"
# Context: Evaluation Additions / `script` evaluation / Rules.
def test_command_runs_in_a_shell():
    assert run(script("true && exit 0"), {}, "x") is True


# Spec: "exit code equal to `success_exit_code` means pass; any other exit code
# means fail"
# Context: Evaluation Additions / `script` evaluation / Rules.
def test_matching_exit_code_passes_and_others_fail():
    assert run(script("exit 0"), {}, "x") is True
    assert run(script("exit 1"), {}, "x") is False


def test_success_exit_code_may_be_non_zero():
    assert run(script("exit 3", success_exit_code=3), {}, "x") is True
    assert run(script("exit 0", success_exit_code=3), {}, "x") is False


# Spec: "command timeout is 10 seconds; timeout is a failed evaluation"
# Context: Evaluation Additions / `script` evaluation / Rules.
def test_timeout_is_ten_seconds():
    assert ScriptConfig(command_template="x", success_exit_code=0).timeout == 10.0


def test_timeout_is_a_failed_evaluation():
    config = ScriptConfig(command_template="sleep 5", success_exit_code=0, timeout=0.2)
    assert run(config, {}, "x") is False


# Spec: "capture command stdout and stderr, but do not include them in the
# JSONL output"
# Context: Evaluation Additions / `script` evaluation / Rules.
def test_command_output_is_not_in_the_jsonl(write_yaml, write_inputs, run_args, workdir):
    document = {"defaults": base_defaults("placeholder"), "tasks": {"code_gen": script_task()}}
    # The markers are assembled at run time so the command text in `input`
    # cannot be mistaken for captured output.
    row = {"problem": "p", "test_code": "printf 'ST%s\\n' DOUT_MARK; printf 'ST%s\\n' DERR_MARK >&2"}
    with FakeAPI(responder=always("def f(): pass")) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs({"code_gen": [row]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    assert result.returncode == 0
    text = (result.output_path / "code_gen.jsonl").read_text()
    assert "STDOUT_MARK" not in text and "STDERR_MARK" not in text
    assert task_rows(result, "code_gen")[0]["result"]["passed"] is True


# Spec: "If the row contains {"problem": ..., "test_code": "echo
# '{__response__}' | grep -q 'good code'"} ... A zero exit code passes;
# non-zero fails."
# Context: Examples / Script evaluation example.
def test_script_example_from_the_spec(write_yaml, write_inputs, run_args, workdir):
    document = {"defaults": base_defaults("placeholder"), "tasks": {"code_gen": script_task()}}
    test_code = "echo '{__response__}' | grep -q 'good code'"
    rows = [
        {"problem": "write good code", "test_code": test_code},
        {"problem": "write bad code", "test_code": test_code},
    ]
    responder = by_question(
        {
            "write good code": Reply(content="this is good code"),
            "write bad code": Reply(content="this is rubbish"),
        }
    )
    with FakeAPI(responder=responder) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs({"code_gen": rows})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    assert result.returncode == 0
    assert [written["result"]["passed"] for written in task_rows(result, "code_gen")] == [True, False]


# Spec: the generated response text is what the command sees.
# Context: "then the rendered shell command uses the generated response text in
# place of `__response__`".
def test_response_text_reaches_the_command():
    row = {"test_code": "test '{__response__}' = 'hello world'"}
    assert run(script('bash -c "{test_code}"'), row, "hello world") is True
    assert run(script('bash -c "{test_code}"'), row, "other") is False


# Spec: "evaluation: type: script, command_template: ..., success_exit_code: 0"
# Context: Evaluation Additions; `command_template` is required for the type.
def test_command_template_is_required():
    with pytest.raises(ConfigError):
        build_run_config(
            {
                "defaults": base_defaults("http://localhost:8000"),
                "tasks": {"a": script_task(evaluation={"type": "script"})},
            },
            {},
        )


# Spec: "success_exit_code: 0" in the example config.
# Context: Evaluation Additions; omitted means the documented default.
def test_success_exit_code_defaults_to_zero():
    config = build_run_config(
        {
            "defaults": base_defaults("http://localhost:8000"),
            "tasks": {"a": script_task(evaluation={"type": "script", "command_template": "true"})},
        },
        {},
    )
    assert config.tasks["a"].evaluation.script.success_exit_code == 0


# Spec: "make up to `n` attempts and keep the first passing response" (Part 1)
# combined with script evaluation.
# Context: script evaluation drives rejection sampling like any other type.
def test_script_evaluation_drives_rejection(write_yaml, write_inputs, run_args, workdir):
    task = script_task(generation={"scheme": "rejection", "temperature": 0.8, "n": 3})
    document = {"defaults": base_defaults("placeholder"), "tasks": {"code_gen": task}}
    row = {"problem": "p", "test_code": "echo '{__response__}' | grep -q ok"}
    replies = [Reply(content="bad"), Reply(content="still bad"), Reply(content="ok now")]
    with FakeAPI(responder=sequence(replies)) as api:
        document["defaults"]["api_url"] = api.url
        config = write_yaml(document)
        data = write_inputs({"code_gen": [row]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    written = task_rows(result, "code_gen")[0]
    assert written["result"]["attempts"] == 3
    assert written["result"]["passed"] is True
    assert written["output"] == {"code": "ok now"}

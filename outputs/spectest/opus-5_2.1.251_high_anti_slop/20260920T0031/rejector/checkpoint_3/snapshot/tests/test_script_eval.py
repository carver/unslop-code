"""Shell command rendering and the exit code that decides a row."""

import asyncio

from evaluation import EvaluationConfig
from script_eval import run_script
from templates import render_command


def config(command_template, success_exit_code=0):
    return EvaluationConfig(
        type="script",
        extract="full",
        command_template=command_template,
        success_exit_code=success_exit_code,
    )


def run(command_template, text, row=None, success_exit_code=0):
    return asyncio.run(run_script(config(command_template, success_exit_code), text, row or {}))


def test_zero_exit_code_passes():
    assert run("python3 -c \"assert '{__response__}' == 'ok'\"", "ok").passed is True


def test_non_zero_exit_code_fails():
    assert run("python3 -c \"assert '{__response__}' == 'ok'\"", "nope").passed is False


def test_configured_success_code_is_the_one_compared():
    assert run("exit 3", "ok", success_exit_code=3).passed is True
    assert run("exit 0", "ok", success_exit_code=3).passed is False


def test_a_row_field_may_bring_its_own_response_placeholder():
    row = {"test_code": "echo '{__response__}' | grep -q 'good code'"}
    assert run('bash -c "{test_code}"', "this is good code", row).passed is True
    assert run('bash -c "{test_code}"', "this is bad code", row).passed is False


def test_braces_in_the_response_are_left_alone():
    row = {"test_code": "echo '{__response__}' | grep -q 'def f()'"}
    assert render_command("{test_code}", row, "def f(): {x}") == "echo 'def f(): {x}' | grep -q 'def f()'"


def test_timeout_is_a_failed_evaluation(monkeypatch):
    monkeypatch.setattr("script_eval.TIMEOUT_SECONDS", 0.2)
    assert run("sleep 5", "ok").passed is False


def test_command_output_is_not_reported():
    outcome = run("echo noisy; echo loud >&2", "ok")
    assert (outcome.passed, outcome.extracted) == (True, None)

"""Script evaluation and the judge's score parsing."""

import asyncio

from config import EvaluationConfig
from verdicts import evaluate_response


def verdict(config, text, row):
    return asyncio.run(evaluate_response(config, text, row, client=None))


def script_config(command_template, success_exit_code=0):
    return EvaluationConfig(
        type="script",
        extract="full",
        command_template=command_template,
        success_exit_code=success_exit_code,
    )


def test_exit_code_decides_the_verdict():
    config = script_config("python3 -c \"{test_code}\"")
    row = {"test_code": "raise SystemExit(0)"}
    assert verdict(config, "ignored", row).passed is True

    assert verdict(script_config("exit 3"), "ignored", {}).passed is False
    assert verdict(script_config("exit 3", success_exit_code=3), "ignored", {}).passed is True


def test_response_reaches_a_command_built_from_a_row_field():
    config = script_config("{test_code}")
    row = {"test_code": "echo '{__response__}' | grep -q 'good code'"}
    assert verdict(config, "def f(): return 'good code'", row).passed is True
    assert verdict(config, "def f(): return 'bad code'", row).passed is False


def test_response_reaches_the_command_template_directly():
    config = script_config("echo '{__response__}' | grep -q hello")
    assert verdict(config, "hello there", {}).passed is True


def test_a_slow_command_fails(monkeypatch):
    monkeypatch.setattr("verdicts.SCRIPT_TIMEOUT_SECONDS", 0.2)
    assert verdict(script_config("sleep 5"), "ignored", {}).passed is False


def test_no_evaluation_yields_an_empty_verdict():
    assert verdict(None, "anything", {}).passed is None

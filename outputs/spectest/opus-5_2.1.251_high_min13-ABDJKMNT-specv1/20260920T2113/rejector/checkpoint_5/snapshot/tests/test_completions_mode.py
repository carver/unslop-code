"""`api_type: completions`: config, CLI flags, request path and payload shape."""

from __future__ import annotations

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import multi_config, task_config
from tests.fake_api import COMPLETIONS_PATH, text_ok

ROW = {"question": "What is 2 + 3?", "answer": "5"}


def completions_task(server, **overrides) -> dict:
    return task_config(api_url=server.url, api_type="completions",
                       chat_template="llama3", **overrides)


# 'When api_type is "completions", send requests to {api_url}/v1/completions'
def test_requests_go_to_the_completions_path(cli, api):
    server = api(lambda index, body: text_ok("#### 5"))
    run = cli.run(completions_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    assert [call.path for call in server.log.calls] == [COMPLETIONS_PATH]


# "completions requests send prompt, temperature, max_tokens, and model"
def test_completions_payload_carries_exactly_the_documented_fields(cli, api):
    server = api(lambda index, body: text_ok("#### 5"))
    run = cli.run(completions_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    body = server.log.bodies[0]
    assert set(body) == {"model", "prompt", "temperature", "max_tokens"}
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 256
    assert isinstance(body["prompt"], str)


# "with a rendered prompt string instead of a messages array"
def test_the_prompt_is_the_rendered_template(cli, api):
    server = api(lambda index, body: text_ok("#### 5"))
    run = cli.run(completions_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    prompt = server.log.prompts[0]
    assert "messages" not in server.log.bodies[0]
    assert prompt.startswith("<|begin_of_text|>")
    assert "Solve the math problem. Final answer after ####." in prompt
    assert ROW["question"] in prompt


# "completions responses return choices[].text, not choices[].message"
def test_output_is_read_from_choices_text(cli, api):
    server = api(lambda index, body: text_ok("2 + 3 = 5\n#### 5", prompt_tokens=200,
                                             completion_tokens=50))
    run = cli.run(completions_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"]["passed"] is True
    assert row["meta"]["prompt_tokens"] == 200
    assert row["meta"]["completion_tokens"] == 50
    assert row["meta"]["finish_reason"] == "stop"


# "defaults: api_type: "completions" / chat_template: "llama3""
def test_api_type_and_template_come_from_defaults(cli):
    config = multi_config("gsm8k", defaults={"api_type": "completions",
                                             "chat_template": "llama3"})
    task = load_config(cli.write_config(config)).tasks["gsm8k"]
    assert task.api_type == "completions"
    assert task.chat_template == "llama3"


# 'tasks: gsm8k: api_type: "completions" / chat_template: "chatml"'
def test_a_task_overrides_the_default_api_type(cli):
    config = multi_config("gsm8k", "mmlu", defaults={"api_type": "chat"})
    config["tasks"]["gsm8k"].update(api_type="completions", chat_template="chatml")
    tasks = load_config(cli.write_config(config)).tasks
    assert (tasks["gsm8k"].api_type, tasks["gsm8k"].chat_template) == \
        ("completions", "chatml")
    assert tasks["mmlu"].api_type == "chat"


# Chat is the mode every earlier checkpoint used, so it stays the default.
def test_api_type_defaults_to_chat(cli):
    task = load_config(cli.write_config(task_config())).only
    assert task.api_type == "chat"
    assert task.chat_template == "chatml"


@pytest.mark.parametrize("field,value", [
    ("api_type", "grpc"), ("chat_template", "alpaca"),
])
def test_unknown_api_type_or_template_is_a_config_error(cli, field, value):
    with pytest.raises(ConfigError, match=field):
        load_config(cli.write_config(task_config(**{field: value})))


# "--api-type <chat|completions>" / "When provided, these CLI flags override the
#  config values."
def test_api_type_flag_overrides_the_config(cli, api):
    server = api(lambda index, body: text_ok("#### 5"))
    run = cli.run(task_config(api_url=server.url), [ROW],
                  "--api-type", "completions", "--chat-template", "chatml")
    assert run.returncode == 0, run.stderr
    assert [call.path for call in server.log.calls] == [COMPLETIONS_PATH]
    assert server.log.prompts[0].startswith("<|im_start|>system")


# "--chat-template <chatml|llama3|mistral|zephyr>"
def test_chat_template_flag_overrides_the_config(cli, api):
    server = api(lambda index, body: text_ok("#### 5"))
    run = cli.run(completions_task(server), [ROW], "--chat-template", "zephyr")
    assert run.returncode == 0, run.stderr
    assert server.log.prompts[0].startswith("<|system|>")


@pytest.mark.parametrize("flag,value", [
    ("--api-type", "grpc"), ("--chat-template", "alpaca"),
])
def test_cli_rejects_unknown_values(cli, flag, value):
    run = cli.run(task_config(), [ROW], flag, value)
    assert run.returncode == 2
    assert "invalid choice" in run.stderr


# The flags apply to every task a multi-task run selects.
def test_flags_apply_across_tasks(cli, api):
    server = api(lambda index, body: text_ok("#### 5"))
    config = multi_config("gsm8k", "mmlu", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"gsm8k": [ROW], "mmlu": [dict(ROW, a="1", b="2",
                                                               c="3", d="4")]},
                        "--api-type", "completions")
    assert run.returncode == 0, run.stderr
    assert {call.path for call in server.log.calls} == {COMPLETIONS_PATH}


# 5xx handling is shared with chat mode: the request is retried, then gives up.
def test_completions_errors_still_retry_and_fail_the_row(cli, api):
    server = api(lambda index, body: {"status": 500, "payload": {}})
    run = cli.run(completions_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 3
    assert run.rows[0]["output"] is None

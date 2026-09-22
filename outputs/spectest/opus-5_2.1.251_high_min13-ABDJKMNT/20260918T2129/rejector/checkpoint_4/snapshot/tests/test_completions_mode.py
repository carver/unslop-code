"""`api_type: completions`: endpoint, payload, response shape, and flags."""

from __future__ import annotations

from conftest import GSM8K_TASK, base_config, multi_config
from fake_server import FakeAPIServer, Reply, always, text_completion

ROW = {"question": "2+3?", "answer": "5"}
ANSWER = "Adding gives #### 5"


def _answers(payload, index):
    return Reply(text_completion(ANSWER, prompt_tokens=200, completion_tokens=50))


def _run(write_config, write_input, run_cli, config_map, *extra, responder=None, rows=None):
    with FakeAPIServer(responder or _answers) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
        result.paths = api.paths
    return result


def _completions_config(**task_overrides) -> dict:
    """A single-task config that talks to `/v1/completions`."""
    return base_config("", api_type="completions", chat_template="chatml", **task_overrides)


# Spec: "When api_type is "completions", send requests to
# {api_url}/v1/completions"
def test_requests_go_to_the_completions_endpoint(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _completions_config())

    assert result.paths == ["/v1/completions"]


# Spec: "with a rendered prompt string instead of a messages array"
def test_request_sends_a_prompt_string(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _completions_config())

    assert isinstance(result.payloads[0]["prompt"], str)
    assert "messages" not in result.payloads[0]


# Spec: "completions requests send `prompt`, `temperature`, `max_tokens`, and
# `model`"
def test_request_carries_exactly_the_documented_fields(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _completions_config())

    assert set(result.payloads[0]) == {"model", "prompt", "temperature", "max_tokens"}
    assert result.payloads[0]["model"] == "gpt-4"
    assert result.payloads[0]["max_tokens"] == 512


# Spec: "completions responses return choices[].text, not choices[].message"
def test_output_is_read_from_choices_text(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _completions_config())

    assert result.rows[0]["output"] == {"solution": ANSWER}
    assert result.rows[0]["result"]["passed"] is True


# Spec: the completions response example carries `usage` and `finish_reason`
def test_usage_and_finish_reason_are_recorded(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _completions_config())

    meta = result.rows[0]["meta"]
    assert meta["prompt_tokens"] == 200
    assert meta["completion_tokens"] == 50
    assert meta["finish_reason"] == "stop"


# Spec: "defaults: api_type: "completions" / chat_template: "llama3""
def test_api_type_can_be_set_in_defaults(write_config, write_input, run_argv):
    config_map = multi_config("", {"gsm8k": dict(GSM8K_TASK)}, api_type="completions", chat_template="llama3")
    with FakeAPIServer(_answers) as api:
        config_map["defaults"]["api_url"] = api.url
        config = write_config(config_map)
        rows = write_input([ROW], name="gsm8k.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={rows}", output="out")
        paths, payloads = api.paths, api.payloads

    assert result.returncode == 0
    assert paths == ["/v1/completions"]
    assert payloads[0]["prompt"].startswith("<|begin_of_text|>")


# Spec: "Per-task override: tasks: gsm8k: api_type: "completions" /
# chat_template: "chatml""
def test_task_overrides_the_default_api_type(write_config, write_input, run_argv):
    tasks = {"gsm8k": {**GSM8K_TASK, "api_type": "completions", "chat_template": "chatml"}}
    config_map = multi_config("", tasks, api_type="chat")
    with FakeAPIServer(_answers) as api:
        config_map["defaults"]["api_url"] = api.url
        config = write_config(config_map)
        rows = write_input([ROW], name="gsm8k.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={rows}", output="out")
        paths = api.paths

    assert result.returncode == 0
    assert paths == ["/v1/completions"]


# Spec: "--api-type <chat|completions> ... When provided, these CLI flags
# override the config values."
def test_api_type_flag_overrides_the_config(write_config, write_input, run_cli):
    config_map = base_config("", api_type="chat")
    result = _run(
        write_config, write_input, run_cli, config_map,
        "--api-type", "completions", "--chat-template", "llama3",
    )

    assert result.paths == ["/v1/completions"]
    assert result.payloads[0]["prompt"].startswith("<|begin_of_text|>")


# Spec: "--chat-template <chatml|llama3|mistral|zephyr>" overriding the config
def test_chat_template_flag_overrides_the_config(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, _completions_config(), "--chat-template", "zephyr"
    )

    assert result.payloads[0]["prompt"].startswith("<|system|>")


# Spec: "--api-type <chat|completions>" - other values are rejected
def test_unknown_api_type_flag_is_rejected(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, base_config(""), "--api-type", "responses")

    assert result.returncode == 1


# Spec: "--chat-template <chatml|llama3|mistral|zephyr>" - other values are
# rejected
def test_unknown_chat_template_in_config_is_rejected(write_config, write_input, run_cli):
    config_map = base_config("", api_type="completions", chat_template="alpaca")
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.returncode == 1
    assert "alpaca" in result.stderr


# Spec: "api_type" is chat unless configured otherwise - part 1 behaviour
def test_chat_remains_the_default_api_type(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, base_config(""), responder=always(ANSWER))

    assert result.paths == ["/v1/chat/completions"]

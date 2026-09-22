"""`api_type: completions`: rendered prompts against `/v1/completions`."""

from __future__ import annotations

from conftest import exact_match_task, make_config, make_multi_config

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]
ROWS = {"gsm8k": [{"question": "2+3?", "answer": "42"}]}


def completions_config(server_url, **overrides):
    settings = {"api_type": "completions", "chat_template": "llama3", **overrides}
    return make_config(server_url, **settings)


# Spec: "When `api_type` is `\"completions\"`, send requests to
# `{api_url}/v1/completions`".
def test_requests_go_to_the_completions_endpoint(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(completions_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.paths == ["/v1/completions"]


# Spec: "completions requests send `prompt`, `temperature`, `max_tokens`, and
# `model`" -- and "a rendered prompt string instead of a messages array".
def test_completions_payload_shape(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(completions_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    payload = server.payloads[0]
    assert set(payload) == {"model", "prompt", "temperature", "max_tokens"}
    assert payload["model"] == "gpt-4"
    assert payload["max_tokens"] == 512
    assert payload["temperature"] == 0.0


# Spec: "chat_template: llama3" -- the configured template renders the prompt.
def test_prompt_uses_the_configured_template(servers, run_cli):
    server = servers(contents=["#### 42"])
    run_cli(completions_config(server.url), ROW)
    prompt = server.payloads[0]["prompt"]
    assert prompt.startswith("<|begin_of_text|><|start_header_id|>system<|end_header_id|>")
    assert "What is 15 + 27?" in prompt
    assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


# Spec: "completions responses return `choices[].text`, not `choices[].message`"
# -- "reads the model output from `choices[0].text`".
def test_output_is_read_from_choices_text(servers, run_cli):
    server = servers(contents=["The answer is 42"])
    result = run_cli(completions_config(server.url), ROW)
    assert result.rows[0]["output"] == {"solution": "The answer is 42"}
    assert result.rows[0]["result"]["passed"] is True


# Spec: completions rows keep the usual metadata, read from the same `usage`.
def test_usage_is_tallied_for_completions_runs(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(completions_config(server.url), ROW)
    assert result.rows[0]["meta"]["prompt_tokens"] == 45
    assert result.summary["total_completion_tokens"] == 120


# Spec: "defaults: api_type: \"completions\" chat_template: \"llama3\"".
def test_defaults_supply_the_api_type(servers, run_multi):
    server = servers(contents=["#### 42"])
    config = make_multi_config(
        server.url,
        {"gsm8k": exact_match_task()},
        api_type="completions",
        chat_template="chatml",
    )
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert server.paths == ["/v1/completions"]
    assert server.payloads[0]["prompt"].startswith("<|im_start|>system\n")


# Spec: "Per-task override: tasks: gsm8k: api_type: \"completions\"
# chat_template: \"chatml\"".
def test_task_overrides_the_default_api_type(servers, run_multi):
    server = servers(contents=["#### 42"])
    config = make_multi_config(
        server.url,
        {
            "chatty": exact_match_task(),
            "gsm8k": exact_match_task(api_type="completions", chat_template="chatml"),
        },
        api_type="chat",
    )
    result = run_multi(config, {"gsm8k": ROWS["gsm8k"], "chatty": ROWS["gsm8k"]})
    assert result.exit_code == 0, result.stderr
    assert set(server.paths) == {"/v1/completions", "/v1/chat/completions"}
    completions = [
        payload for path, payload in zip(server.paths, server.payloads)
        if path == "/v1/completions"
    ]
    assert completions[0]["prompt"].startswith("<|im_start|>system\n")


# Spec: "--api-type <chat|completions> ... When provided, these CLI flags
# override the config values."
def test_cli_api_type_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(server.url, api_type="chat")
    result = run_cli(config, ROW, "--api-type", "completions", "--chat-template", "llama3")
    assert result.exit_code == 0, result.stderr
    assert server.paths == ["/v1/completions"]


# Spec: "--chat-template <chatml|llama3|mistral|zephyr> ... override the config
# values".
def test_cli_chat_template_overrides_the_config(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(completions_config(server.url), ROW, "--chat-template", "zephyr")
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["prompt"].startswith("<|system|>\n")


# Spec: the rendered prompt is the whole conversation, so ICL turns are part of
# it too.
def test_icl_turns_are_rendered_into_the_prompt(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = completions_config(
        server.url,
        chat_template="chatml",
        icl={
            "setups": [
                {
                    "name": "direct",
                    "examples": [{"input": {"question": "1+1?"}, "output": "#### 2"}],
                }
            ]
        },
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    prompt = server.payloads[0]["prompt"]
    assert "<|im_start|>user\n1+1?<|im_end|>" in prompt
    assert "<|im_start|>assistant\n#### 2<|im_end|>" in prompt

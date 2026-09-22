"""Template-driven requests against `/v1/completions`."""

from __future__ import annotations

import pytest

from conftest import base_task, icl_block, inline_setup, judge_task
from fake_api import FakeAPI, Reply, always, sequence

ROW = {"question": "2 + 3?", "answer": "5"}


def completions_task(api_url: str, template: str = "chatml", **overrides) -> dict:
    """The Part 1 task, rerouted through the completions endpoint."""
    return base_task(api_url, api_type="completions", chat_template=template, **overrides)


# Spec: "When `api_type` is `\"completions\"`, send requests to
# `{api_url}/v1/completions`"
# Context: Completions Mode.
def test_requests_go_to_the_completions_endpoint(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        run_cli(write_config(completions_task(api.url)), write_input([ROW]))
        assert api.paths == ["/v1/completions"]


# Spec: "with a rendered prompt string instead of a messages array" /
# "completions requests send `prompt`, `temperature`, `max_tokens`, and
# `model`"
# Context: Completions Mode / Rules.
def test_request_body_matches_the_documented_shape(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        run_cli(write_config(completions_task(api.url)), write_input([ROW]))
        body = api.requests[0]
    assert set(body) == {"model", "prompt", "temperature", "max_tokens"}
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512
    assert body["prompt"].endswith("<|im_start|>assistant\n")


# Spec: "completions responses return `choices[].text`, not `choices[].message`"
# Context: Completions Mode / Rules.
def test_output_is_read_from_choices_text(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        result = run_cli(write_config(completions_task(api.url)), write_input([ROW]))
    assert result.rows[0]["output"] == {"solution": "#### 5"}
    assert result.rows[0]["result"]["passed"] is True


# Spec: the completions response example's `usage` and `finish_reason`.
# Context: Completions Mode / Request and response shape.
def test_usage_and_finish_reason_reach_the_record(write_config, write_input, run_cli):
    reply = Reply(content="#### 5", prompt_tokens=200, completion_tokens=50)
    with FakeAPI(responder=sequence([reply])) as api:
        result = run_cli(write_config(completions_task(api.url)), write_input([ROW]))
    meta = result.rows[0]["meta"]
    assert meta["prompt_tokens"] == 200
    assert meta["completion_tokens"] == 50
    assert meta["total_tokens"] == 250
    assert meta["finish_reason"] == "stop"


# Spec: "`--chat-template <chatml|llama3|mistral|zephyr>`"
# Context: Completions Mode; each built-in drives a real request.
@pytest.mark.parametrize(
    "template,marker",
    [
        ("chatml", "<|im_start|>system\n"),
        ("llama3", "<|begin_of_text|>"),
        ("mistral", "[INST] "),
        ("zephyr", "<|system|>\n"),
    ],
)
def test_each_built_in_template_renders_the_prompt(
    template, marker, write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 5")) as api:
        run_cli(write_config(completions_task(api.url, template)), write_input([ROW]))
        prompt = api.requests[0]["prompt"]
    assert marker in prompt
    assert "Solve the math problem. Put your final answer after ####." in prompt
    assert "2 + 3?" in prompt


# Spec: "built-in templates must handle multi-turn conversations by repeating
# the correct role markers for every message"
# Context: Completions Mode / Rules; ICL demonstrations are the extra turns.
def test_icl_demonstrations_become_extra_turns(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = completions_task(api.url)
        task["icl"] = icl_block([inline_setup("cot", "#### 4")])
        run_cli(write_config(task), write_input([ROW]))
        prompt = api.requests[0]["prompt"]
    assert prompt.count("<|im_start|>user\n") == 2
    assert "<|im_start|>assistant\n#### 4<|im_end|>\n" in prompt


# Spec: "Existing behavior from earlier parts is unchanged unless stated here."
# Context: Completions Mode; the judge call uses the task's endpoint too.
def test_judge_calls_use_the_same_endpoint(write_config, write_input, run_cli):
    with FakeAPI(responder=always("9")) as api:
        task = judge_task(
            api_url=api.url,
            model="gpt-4",
            rpm=600,
            api_type="completions",
            chat_template="zephyr",
        )
        rows = [{"prompt_text": "Write a haiku", "criteria": "vivid"}]
        result = run_cli(write_config(task), write_input(rows))
        assert api.paths == ["/v1/completions", "/v1/completions"]
    assert result.rows[0]["result"]["judge_score"] == 9


# Spec: "send requests to `{api_url}/v1/completions`"
# Context: Completions Mode; a trailing slash on `api_url` must not double up.
def test_api_url_trailing_slash_is_tolerated(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        run_cli(write_config(completions_task(api.url + "/")), write_input([ROW]))
        assert api.paths == ["/v1/completions"]

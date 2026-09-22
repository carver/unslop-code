"""Checkpoint 4 completions mode: `/v1/completions` requests driven by a
rendered chat template."""

import json

import pytest

from fake_api import FakeAPI, text_completion, completion


def responder(text="#### 8", finish_reason="stop", prompt_tokens=200,
              completion_tokens=50):
    def _responder(rec):
        return 200, text_completion(text, prompt_tokens, completion_tokens,
                                    finish_reason)
    return _responder


COMPLETIONS = {"api_type": "completions", "chat_template": "chatml"}


# "When `api_type` is `"completions"`, send requests to
#  `{api_url}/v1/completions`"
def test_requests_go_to_the_completions_endpoint(run_task):
    with FakeAPI(responder()) as server:
        run_task(server=server, task=COMPLETIONS, check=0)
    assert [r.path for r in server.requests] == ["/v1/completions"]


def test_chat_mode_still_uses_chat_completions(run_task):
    with FakeAPI() as server:
        run_task(server=server, task={"api_type": "chat"}, check=0)
    assert [r.path for r in server.requests] == ["/v1/chat/completions"]


def test_default_api_type_is_chat(run_task):
    with FakeAPI() as server:
        run_task(server=server, check=0)
    assert server.requests[0].path == "/v1/chat/completions"


# "with a rendered prompt string instead of a messages array"
# "completions requests send `prompt`, `temperature`, `max_tokens`, and
#  `model`"
def test_request_body_shape(run_task):
    with FakeAPI(responder()) as server:
        run_task(server=server, task=COMPLETIONS, check=0)
    body = server.requests[0].body
    assert set(body) == {"model", "prompt", "temperature", "max_tokens"}
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512
    assert isinstance(body["prompt"], str)
    assert "messages" not in body


def test_cli_overrides_reach_the_completions_body(run_task):
    with FakeAPI(responder()) as server:
        run_task(server=server, task=COMPLETIONS,
                 extra=["--max-tokens", "64", "--model", "other"], check=0)
    body = server.requests[0].body
    assert body["max_tokens"] == 64 and body["model"] == "other"


# "completions responses return `choices[].text`, not `choices[].message`"
def test_output_is_read_from_choices_text(run_task):
    with FakeAPI(responder("The answer is #### 5")) as server:
        res = run_task(server=server, task=COMPLETIONS, check=0)
    row = res.rows[0]
    assert row["output"] == {"solution": "The answer is #### 5"}
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "5"


def test_usage_and_finish_reason_are_recorded(run_task):
    with FakeAPI(responder("#### 5", finish_reason="length",
                           prompt_tokens=200, completion_tokens=50)) as server:
        res = run_task(server=server, task=COMPLETIONS, check=0)
    meta = res.rows[0]["meta"]
    assert meta["prompt_tokens"] == 200
    assert meta["completion_tokens"] == 50
    assert meta["total_tokens"] == 250
    assert meta["finish_reason"] == "length"
    assert res.summary["total_prompt_tokens"] == 200


def test_a_chat_shaped_response_is_not_accepted_in_completions_mode(run_task):
    # The server answers with `choices[].message`: no text, so the row fails.
    with FakeAPI(lambda rec: (200, completion("#### 5"))) as server:
        res = run_task(server=server, task=COMPLETIONS, check=0)
    assert res.rows[0]["output"] is None
    assert res.summary["failed"] == 1


# "defaults: api_type: "completions", chat_template: "llama3""
def test_api_type_from_multi_task_defaults(run_multi):
    with FakeAPI(responder("#### 5")) as server:
        run_multi(server, defaults={"api_type": "completions",
                                    "chat_template": "llama3"}, check=0)
    assert {r.path for r in server.requests} == {"/v1/completions"}
    assert all("<|begin_of_text|>" in r.prompt for r in server.requests)


# "Per-task override: tasks: gsm8k: api_type: "completions",
#  chat_template: "chatml""
def test_per_task_api_type_override(run_multi):
    with FakeAPI(lambda rec: (200, text_completion("#### 5")
                              if rec.is_completions else completion("B"))
                 ) as server:
        run_multi(server,
                  tasks={"gsm8k": {"api_type": "completions",
                                   "chat_template": "chatml"}}, check=0)
    paths = {r.path for r in server.requests}
    assert paths == {"/v1/completions", "/v1/chat/completions"}
    completions = [r for r in server.requests if r.is_completions]
    assert "<|im_start|>" in completions[0].prompt


def test_per_task_chat_template_overrides_defaults(run_multi):
    with FakeAPI(responder("#### 5")) as server:
        run_multi(server, defaults={"api_type": "completions",
                                    "chat_template": "llama3"},
                  tasks={"gsm8k": {"chat_template": "chatml"}}, check=0)
    by_task = {}
    for rec in server.requests:
        by_task["im_start" if "<|im_start|>" in rec.prompt else "llama"] = rec
    assert set(by_task) == {"im_start", "llama"}


# "CLI flags: --api-type <chat|completions>, --chat-template
#  <chatml|llama3|mistral|zephyr>.  When provided, these CLI flags override
#  the config values."
def test_cli_api_type_overrides_the_config(run_task):
    with FakeAPI(responder("#### 5")) as server:
        run_task(server=server, task={"api_type": "chat"},
                 extra=["--api-type", "completions",
                        "--chat-template", "chatml"], check=0)
    assert server.requests[0].path == "/v1/completions"


def test_cli_chat_template_overrides_the_config(run_task):
    with FakeAPI(responder("#### 5")) as server:
        run_task(server=server,
                 task={"api_type": "completions", "chat_template": "chatml"},
                 extra=["--chat-template", "zephyr"], check=0)
    assert server.requests[0].prompt.startswith("<|system|>")


def test_cli_api_type_chat_overrides_a_completions_config(run_task):
    with FakeAPI() as server:
        run_task(server=server, task=COMPLETIONS,
                 extra=["--api-type", "chat"], check=0)
    assert server.requests[0].path == "/v1/chat/completions"


def test_cli_api_type_applies_to_every_task(run_multi):
    with FakeAPI(responder("#### 5")) as server:
        run_multi(server, extra=["--api-type", "completions",
                                 "--chat-template", "mistral"], check=0)
    assert {r.path for r in server.requests} == {"/v1/completions"}


@pytest.mark.parametrize("flag,value", [("--api-type", "grpc"),
                                        ("--chat-template", "alpaca")])
def test_invalid_cli_values_are_rejected(run_task, flag, value):
    with FakeAPI() as server:
        res = run_task(server=server, extra=[flag, value], check=1)
    assert res.stderr


def test_invalid_api_type_in_the_config_is_rejected(run_task):
    with FakeAPI() as server:
        res = run_task(server=server, task={"api_type": "grpc"}, check=1)
    assert "api_type" in res.stderr


def test_invalid_chat_template_in_the_config_is_rejected(run_task):
    with FakeAPI() as server:
        res = run_task(server=server,
                       task={"api_type": "completions",
                             "chat_template": "alpaca"}, check=1)
    assert "chat_template" in res.stderr


# The rest of the pipeline is unchanged in completions mode.
def test_rejection_sampling_works_in_completions_mode(run_task):
    texts = ["#### 1", "#### 5"]

    def _responder(rec):
        return 200, text_completion(texts[min(rec.index, 1)])
    with FakeAPI(_responder) as server:
        res = run_task(server=server,
                       task={"api_type": "completions",
                             "chat_template": "chatml",
                             "generation": {"scheme": "rejection",
                                            "temperature": 0.7, "n": 3}},
                       check=0)
    row = res.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 2
    assert len(row["meta"]) == 2

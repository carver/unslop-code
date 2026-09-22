"""Spec section: Part 4 / Completions Mode."""
from __future__ import annotations

from conftest import GSM8K_TASK, base_config, multi_config
from mock_server import MockAPI, always, text_completion


ROW = {"question": "What is 15 + 27?", "answer": "42"}
ANSWER = "15 + 27 = 42\n#### 42"


def text_always(content, **kw):
    body = text_completion(content, **kw)
    return lambda req, i: (200, body)


def completions_config(api_url, template="chatml", **overrides):
    return base_config(api_url, api_type="completions",
                       chat_template=template, **overrides)


# ---------------------------------------------------------------------------
# Phrase: "When `api_type` is `\"completions\"`, send requests to
#          `{api_url}/v1/completions`"
# Context: Part 4 / Completions Mode.
# ---------------------------------------------------------------------------
def test_completions_endpoint(run_tool, write_config, write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        paths = list(api.paths)
    assert res.returncode == 0, res
    assert paths == ["/v1/completions"]


# Context: same phrase - chat mode keeps the old endpoint.
def test_chat_mode_keeps_chat_completions_endpoint(run_tool, write_config,
                                                   write_input):
    with MockAPI(always(ANSWER)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        paths = list(api.paths)
    assert res.returncode == 0, res
    assert paths == ["/v1/chat/completions"]


# ---------------------------------------------------------------------------
# Phrase: "with a rendered prompt string instead of a messages array" /
#         "completions requests send `prompt`, `temperature`, `max_tokens`,
#          and `model`"
# Context: Part 4 / Completions Mode rules and the request shape example.
# ---------------------------------------------------------------------------
def test_completions_request_body(run_tool, write_config, write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url, model="meta-llama/llama-3-70b",
                                              generation={"max_tokens": 512,
                                                          "temperature": 0.0}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        body = api.requests[0]
    assert res.returncode == 0, res
    assert "messages" not in body
    assert isinstance(body["prompt"], str)
    assert body["model"] == "meta-llama/llama-3-70b"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512
    assert set(body) == {"prompt", "model", "temperature", "max_tokens"}


# ---------------------------------------------------------------------------
# Phrase: "completions responses return `choices[].text`, not
#          `choices[].message`"
# Context: Part 4 / Completions Mode rules.
# ---------------------------------------------------------------------------
def test_output_comes_from_choices_text(run_tool, write_config, write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] == {"solution": ANSWER}
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "42"


# Context: same phrase - usage and finish_reason are read as before.
def test_completions_meta(run_tool, write_config, write_input):
    with MockAPI(text_always(ANSWER, prompt_tokens=200, completion_tokens=50,
                             finish_reason="length")) as api:
        cfg = write_config(completions_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    meta = res.rows[0]["meta"]
    assert meta["prompt_tokens"] == 200
    assert meta["completion_tokens"] == 50
    assert meta["total_tokens"] == 250
    assert meta["finish_reason"] == "length"
    assert res.summary["total_prompt_tokens"] == 200
    assert res.summary["total_completion_tokens"] == 50


# ---------------------------------------------------------------------------
# Phrase: "defaults: api_type: \"completions\" / chat_template: \"llama3\""
# Context: Part 4 / Completions Mode config example.
# ---------------------------------------------------------------------------
def test_api_type_from_defaults(run_tool, write_config, write_input, workdir):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(multi_config(
            api.url, {"gsm8k": dict(GSM8K_TASK)},
            defaults={"api_type": "completions", "chat_template": "llama3"}))
        data = write_input([ROW])
        out = str(workdir / "out")
        res = run_tool(cfg, [f"gsm8k={data}"], output=out)
        paths = list(api.paths)
        body = api.requests[0]
    assert res.returncode == 0, res
    assert paths == ["/v1/completions"]
    assert body["prompt"].startswith("<|begin_of_text|>")


# ---------------------------------------------------------------------------
# Phrase: "Per-task override: tasks: gsm8k: api_type: \"completions\" /
#          chat_template: \"chatml\""
# Context: Part 4 / Completions Mode config example.
# ---------------------------------------------------------------------------
def test_per_task_override(run_tool, write_config, write_input, workdir):
    chat_task = dict(GSM8K_TASK)
    completions_task = dict(GSM8K_TASK, api_type="completions",
                            chat_template="chatml")

    def responder(req, i):
        if "prompt" in (req or {}):
            return 200, text_completion(ANSWER)
        from mock_server import completion
        return 200, completion(ANSWER)

    with MockAPI(responder) as api:
        cfg = write_config(multi_config(api.url,
                                        {"chatty": chat_task,
                                         "gsm8k": completions_task}))
        data = write_input([ROW])
        out = str(workdir / "out")
        res = run_tool(cfg, [f"chatty={data}", f"gsm8k={data}"], output=out)
        paths = sorted(api.paths)
    assert res.returncode == 0, res
    assert paths == ["/v1/chat/completions", "/v1/completions"]


# ---------------------------------------------------------------------------
# Phrase: "CLI flags: `--api-type <chat|completions>` /
#          `--chat-template <chatml|llama3|mistral|zephyr>`" and "When
#          provided, these CLI flags override the config values."
# Context: Part 4 / Completions Mode.
# ---------------------------------------------------------------------------
def test_api_type_flag_overrides_config(run_tool, write_config, write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(base_config(api.url, api_type="chat"))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--api-type", "completions",
                                         "--chat-template", "llama3"])
        paths = list(api.paths)
        body = api.requests[0]
    assert res.returncode == 0, res
    assert paths == ["/v1/completions"]
    assert body["prompt"].startswith("<|begin_of_text|>")


def test_chat_template_flag_overrides_config(run_tool, write_config,
                                             write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url, template="chatml"))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--chat-template", "zephyr"])
        body = api.requests[0]
    assert res.returncode == 0, res
    assert body["prompt"].startswith("<|system|>\n")


def test_api_type_flag_can_force_chat(run_tool, write_config, write_input):
    with MockAPI(always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--api-type", "chat"])
        paths = list(api.paths)
    assert res.returncode == 0, res
    assert paths == ["/v1/chat/completions"]


# Context: the flags accept only the documented values.
def test_unknown_api_type_flag_is_rejected(run_tool, write_config,
                                           write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data, extra=["--api-type", "grpc"])
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


def test_unknown_api_type_in_config_is_rejected(run_tool, write_config,
                                                write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(base_config(api.url, api_type="grpc"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
    assert "api_type" in res.stderr


def test_unknown_chat_template_is_rejected(run_tool, write_config,
                                           write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(api.url, template="alpaca"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
    assert "chat_template" in res.stderr or "template" in res.stderr


# ---------------------------------------------------------------------------
# Phrase: "Existing behavior from earlier parts is unchanged unless stated
#          here."
# Context: Part 4 - multi-solution rows keep working over `/v1/completions`.
# ---------------------------------------------------------------------------
def test_num_solutions_in_completions_mode(run_tool, write_config,
                                           write_input):
    with MockAPI(text_always(ANSWER)) as api:
        cfg = write_config(completions_config(
            api.url, num_solutions=2,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2
    assert len(res.rows[0]["output"]) == 2

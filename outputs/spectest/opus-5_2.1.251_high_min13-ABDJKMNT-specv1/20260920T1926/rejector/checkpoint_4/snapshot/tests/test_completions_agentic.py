"""Agentic runs driven through `/v1/completions` and `<tool_call>` text."""

from __future__ import annotations

import pytest

from conftest import agentic_task
from fake_api import FakeAPI, Reply, always, call, turns

ROW = {"question": "How many employees?", "answer": "142"}

LOOKUP = Reply(content=None, tools=(call("lookup", key="employees"),))
FINAL = Reply(content="The company has 142 employees.")


def text_agentic_task(api_url: str, template: str = "chatml") -> dict:
    return agentic_task(api_url, api_type="completions", chat_template=template)


# Spec: "tool definitions are rendered into the prompt instead of being sent
# as a native `tools` field"
# Context: Agentic behavior in completions mode.
def test_tool_definitions_are_rendered_into_the_prompt(write_config, write_input, run_cli):
    with FakeAPI(responder=always("142 employees")) as api:
        run_cli(write_config(text_agentic_task(api.url)), write_input([ROW]))
        body = api.requests[0]
    assert "tools" not in body
    assert "lookup" in body["prompt"]
    assert "Look up a value in the database by key" in body["prompt"]
    assert "calculate" in body["prompt"]
    assert "<tool_call>" in body["prompt"]


# Spec: "parse tool calls from response text blocks of the form `<tool_call>
# {\"name\": \"lookup\", \"arguments\": {\"key\": \"revenue_q1\"}} </tool_call>`"
# Context: Agentic behavior in completions mode.
def test_tool_call_blocks_are_parsed_from_the_text(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        result = run_cli(write_config(text_agentic_task(api.url)), write_input([ROW]))
        assert api.call_count == 2
    assert result.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]


# Spec: "execute those calls and feed the results back into the next prompt
# iteration using the template's tool-role formatting"
# Context: Agentic behavior in completions mode.
def test_results_are_fed_back_with_tool_role_formatting(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        run_cli(write_config(text_agentic_task(api.url)), write_input([ROW]))
        prompt = api.requests[1]["prompt"]
    assert "<|im_start|>tool\n142<|im_end|>\n" in prompt
    assert '<tool_call>\n{"name": "lookup", "arguments": {"key": "employees"}}\n</tool_call>' in prompt


# Spec: "If the response contains final text and no tool calls, stop and use
# that text as the output."
# Context: Agentic behavior in completions mode.
def test_final_text_is_the_output(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        result = run_cli(write_config(text_agentic_task(api.url)), write_input([ROW]))
    row = result.rows[0]
    assert row["output"] == {"answer": "The company has 142 employees."}
    assert row["result"]["iterations"] == 2
    assert row["result"]["passed"] is True
    assert row["meta"]["finish_reason"] == "stop"


# Spec: "execute those calls and feed the results back into the next prompt
# iteration using the template's tool-role formatting"
# Context: Agentic behavior in completions mode; every built-in must carry it.
@pytest.mark.parametrize("template", ["chatml", "llama3", "mistral", "zephyr"])
def test_every_template_carries_tool_results(template, write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        result = run_cli(
            write_config(text_agentic_task(api.url, template)), write_input([ROW])
        )
        assert "142" in api.requests[1]["prompt"]
    assert result.rows[0]["output"] == {"answer": "The company has 142 employees."}


# Spec: "If `max_iterations` is reached first, output `null`"
# Context: Agentic behavior in completions mode.
def test_max_iterations_in_completions_mode(write_config, write_input, run_cli):
    with FakeAPI(responder=always(None, tools=(call("lookup", key="employees"),))) as api:
        task = text_agentic_task(api.url)
        task["generation"]["max_iterations"] = 2
        result = run_cli(write_config(task), write_input([ROW]))
        assert api.call_count == 2
    assert result.rows[0]["output"] is None
    assert result.rows[0]["meta"]["finish_reason"] == "max_iterations"


# Spec: "if one model response contains multiple tool calls, execute and
# record all of them for that iteration"
# Context: Agentic behavior in completions mode; two blocks in one response.
def test_two_blocks_in_one_response(write_config, write_input, run_cli):
    both = (call("lookup", key="revenue_q1"), call("lookup", key="revenue_q2"))
    script = [Reply(content=None, tools=both), Reply(content="2730000")]
    with FakeAPI(responder=turns(script)) as api:
        result = run_cli(write_config(text_agentic_task(api.url)), write_input([ROW]))
    assert [item["result"] for item in result.rows[0]["result"]["tool_calls"]] == [
        "1250000",
        "1480000",
    ]

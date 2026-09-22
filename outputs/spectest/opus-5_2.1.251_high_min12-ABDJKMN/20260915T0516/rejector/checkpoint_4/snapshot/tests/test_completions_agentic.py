"""Part 4: agentic behavior in completions mode."""
import json

import pytest

from conftest import agentic_config, echo_tool, static_map_tool
from mock_api import (MockAPI, agentic_turns, completion_response,
                      tool_call_text)

ROWS = [{"question": "How many employees are there?", "answer": "142"}]
REVENUE = [{"question": "What is the total revenue for Q1 and Q2?",
            "answer": "2730000"}]


def completions_agentic(run_tool, steps, rows=None, template="chatml", **kw):
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url, api_type="completions",
                                      chat_template=template, **kw),
                       rows or ROWS)
    assert run.returncode == 0, run.stderr
    return run, api


# Spec: "tool definitions are rendered into the prompt instead of being sent
#        as a native `tools` field"
# Context: Agentic behavior in completions mode.
def test_tool_definitions_are_rendered_into_the_prompt(run_tool):
    run, api = completions_agentic(run_tool, ["142 employees"])
    payload = api.calls[0]
    assert "tools" not in payload
    prompt = payload["prompt"]
    assert "lookup" in prompt
    assert "Look up a value in the database by key" in prompt
    assert "calculate" in prompt
    assert "<tool_call>" in prompt


def test_tool_definitions_are_rendered_on_every_iteration(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    run, api = completions_agentic(run_tool, steps)
    assert len(api.calls) == 2
    assert all("lookup" in c["prompt"] for c in api.calls)
    assert all("tools" not in c for c in api.calls)


# Spec: "parse tool calls from response text blocks of the form:
#        <tool_call>{"name": "lookup", "arguments": {"key": "revenue_q1"}}
#        </tool_call>"
# Context: Agentic behavior in completions mode.
def test_tool_call_blocks_are_parsed_from_the_response_text(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"})], "It is 1250000."]
    run, api = completions_agentic(run_tool, steps, REVENUE)
    assert run.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"}]
    assert run.rows[0]["result"]["iterations"] == 2


def test_text_with_no_tool_call_block_is_the_final_answer(run_tool):
    run, api = completions_agentic(run_tool, ["The company has 142 employees."])
    assert run.rows[0]["output"] == {"answer": "The company has 142 employees."}
    assert run.rows[0]["result"]["iterations"] == 1
    assert run.rows[0]["result"]["passed"] is True


def test_several_tool_call_blocks_in_one_response(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"}),
              ("lookup", {"key": "revenue_q2"})], "Total: 2730000"]
    run, api = completions_agentic(run_tool, steps, REVENUE)
    calls = run.rows[0]["result"]["tool_calls"]
    assert [c["result"] for c in calls] == ["1250000", "1480000"]
    assert [c["iteration"] for c in calls] == [1, 1]


# Spec: "execute those calls and feed the results back into the next prompt
#        iteration using the template's tool-role formatting"
# Context: Agentic behavior in completions mode.
def test_tool_results_are_fed_back_with_tool_role_markers(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    run, api = completions_agentic(run_tool, steps)
    second = api.calls[1]["prompt"]
    assert "<|im_start|>tool\n142<|im_end|>\n" in second
    assert second.endswith("<|im_start|>assistant\n")


def test_the_assistant_tool_call_text_is_kept_in_the_next_prompt(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    run, api = completions_agentic(run_tool, steps)
    second = api.calls[1]["prompt"]
    assert '<tool_call>\n{"name": "lookup"' in second


def test_llama3_tool_results_use_the_llama3_role_marker(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    run, api = completions_agentic(run_tool, steps, template="llama3")
    second = api.calls[1]["prompt"]
    assert ("<|start_header_id|>tool<|end_header_id|>\n\n142<|eot_id|>"
            in second)


def test_zephyr_tool_results_use_the_zephyr_role_marker(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    run, api = completions_agentic(run_tool, steps, template="zephyr")
    assert "<|tool|>\n142</s>\n" in api.calls[1]["prompt"]


def test_mistral_tool_results_are_wrapped_in_an_instruction_block(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    run, api = completions_agentic(run_tool, steps, template="mistral")
    second = api.calls[1]["prompt"]
    assert "[INST] 142 [/INST]" in second
    assert second.endswith("[/INST]")


# Spec: "If `max_iterations` is reached first, output `null` and use
#        `finish_reason: "max_iterations"`."
# Context: Agentic loop step 5, in completions mode.
def test_max_iterations_in_completions_mode(run_tool):
    steps = [[("lookup", {"key": "employees"})]]
    run, api = completions_agentic(run_tool, steps, max_iterations=3)
    row = run.rows[0]
    assert len(api.calls) == 3
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


# Spec: the agentic output record is the same in completions mode.
# Context: Agentic Output.
def test_completions_agentic_output_record(run_tool):
    steps = [[("lookup", {"key": "revenue_q1"})], "Total is 2730000"]
    run, api = completions_agentic(run_tool, steps, REVENUE)
    row = run.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "2730000"
    assert row["meta"]["total_tokens"] == 2 * 165
    assert [d["finish_reason"] for d in row["meta"]["iterations_detail"]] == \
        ["stop", "stop"]
    assert run.summary["total_api_calls"] == 2


# Spec: "--api-type completions --chat-template llama3 ... This sends
#        requests to `/v1/completions` and reads the model output from
#        `choices[0].text`."
# Context: Examples, Completions-mode run.
def test_cli_flags_drive_an_agentic_completions_run(run_tool):
    steps = [[("lookup", {"key": "employees"})], "The company has 142."]
    with MockAPI(agentic_turns(steps)) as api:
        run = run_tool(agentic_config(api.url), ROWS,
                       args=["--api-type", "completions",
                             "--chat-template", "llama3"])
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/completions", "/v1/completions"]
    assert api.calls[0]["prompt"].startswith("<|begin_of_text|>")
    assert run.rows[0]["output"] == {"answer": "The company has 142."}


# Spec: arguments given as a JSON object inside the block are used directly.
# Context: Agentic behavior in completions mode.
def test_tool_call_block_with_extra_surrounding_text(run_tool):
    call = tool_call_text([("lookup", {"key": "employees"})])

    def responder(payload, i):
        if "142" in payload["prompt"]:
            return 200, completion_response("The company has 142 employees.")
        return 200, completion_response("Let me look that up.\n" + call)

    with MockAPI(responder) as api:
        run = run_tool(agentic_config(api.url, api_type="completions"), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["tool_calls"][0]["args"] == {"key": "employees"}
    assert run.rows[0]["output"] == {"answer": "The company has 142 employees."}

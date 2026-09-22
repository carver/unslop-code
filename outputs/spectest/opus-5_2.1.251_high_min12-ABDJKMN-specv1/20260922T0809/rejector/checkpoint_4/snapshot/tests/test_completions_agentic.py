"""Spec section: Part 4 / Agentic behavior in completions mode."""
from __future__ import annotations

import json

from conftest import (AGENTIC_ROW, CALC_TOOL, LOOKUP_TOOL, agentic_config,
                      agentic_replies)
from mock_server import MockAPI, text_completion


FINAL = "The total revenue for Q1 and Q2 is 2730000."
LOOKUP_Q1 = [("lookup", {"key": "revenue_q1"})]
LOOKUP_BOTH = [("lookup", {"key": "revenue_q1"}),
               ("lookup", {"key": "revenue_q2"})]


def completions_agentic(api_url, tools=None, template="chatml", **kw):
    return agentic_config(api_url, tools if tools is not None else [LOOKUP_TOOL],
                          api_type="completions", chat_template=template, **kw)


def run_loop(write_config, write_input, run_tool, script, **kw):
    with MockAPI(agentic_replies(script)) as api:
        cfg = write_config(completions_agentic(api.url, **kw))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        prompts = [r["prompt"] for r in api.requests]
        paths = list(api.paths)
    return res, prompts, paths


# ---------------------------------------------------------------------------
# Phrase: "tool definitions are rendered into the prompt instead of being sent
#          as a native `tools` field"
# Context: Part 4 / Agentic behavior in completions mode.
# ---------------------------------------------------------------------------
def test_tools_are_rendered_into_the_prompt(run_tool, write_config,
                                            write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(completions_agentic(api.url,
                                               [LOOKUP_TOOL, CALC_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        body = api.requests[0]
    assert res.returncode == 0, res
    assert "tools" not in body
    prompt = body["prompt"]
    assert "lookup" in prompt
    assert LOOKUP_TOOL["description"] in prompt
    assert "calculate" in prompt
    assert CALC_TOOL["description"] in prompt
    # the model is told how to emit a call
    assert "<tool_call>" in prompt
    # and the endpoint is still the completions one
    assert api.paths == ["/v1/completions"]


# ---------------------------------------------------------------------------
# Phrase: "parse tool calls from response text blocks of the form
#          <tool_call>{\"name\": \"lookup\", \"arguments\": {...}}</tool_call>"
# Context: Part 4 / Agentic behavior in completions mode.
# ---------------------------------------------------------------------------
def test_tool_call_block_is_parsed_and_executed(run_tool, write_config,
                                                write_input):
    res, prompts, _ = run_loop(write_config, write_input, run_tool,
                               [LOOKUP_Q1, FINAL])
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"}]
    assert row["result"]["iterations"] == 2
    assert row["output"] == {"answer": FINAL}


# Context: same phrase - several blocks in one response are all executed.
def test_multiple_tool_call_blocks(run_tool, write_config, write_input):
    res, prompts, _ = run_loop(write_config, write_input, run_tool,
                               [LOOKUP_BOTH, FINAL])
    assert res.returncode == 0, res
    calls = res.rows[0]["result"]["tool_calls"]
    assert [(c["iteration"], c["result"]) for c in calls] == [
        (1, "1250000"), (1, "1480000")]


# ---------------------------------------------------------------------------
# Phrase: "execute those calls and feed the results back into the next prompt
#          iteration using the template's tool-role formatting"
# Context: Part 4 / Agentic behavior in completions mode.
# ---------------------------------------------------------------------------
def test_tool_results_are_fed_back_with_tool_role_markers(run_tool,
                                                          write_config,
                                                          write_input):
    res, prompts, _ = run_loop(write_config, write_input, run_tool,
                               [LOOKUP_Q1, FINAL])
    assert res.returncode == 0, res
    second = prompts[1]
    # the assistant's own tool-call text is part of the conversation ...
    assert "<|im_start|>assistant\n<tool_call>" in second
    # ... followed by the handler result in a tool block
    assert "<|im_start|>tool\n1250000<|im_end|>\n" in second
    assert second.endswith("<|im_start|>assistant\n")


def test_tool_role_formatting_follows_the_template(run_tool, write_config,
                                                   write_input):
    res, prompts, _ = run_loop(write_config, write_input, run_tool,
                               [LOOKUP_Q1, FINAL], template="zephyr")
    assert res.returncode == 0, res
    assert "<|tool|>\n1250000</s>\n" in prompts[1]
    assert prompts[1].endswith("<|assistant|>\n")


# ---------------------------------------------------------------------------
# Phrase: "If the response contains final text and no tool calls, stop and use
#          that text as the output."
# Context: Part 4 / Agentic loop, applied to completions mode.
# ---------------------------------------------------------------------------
def test_plain_text_response_ends_the_loop(run_tool, write_config,
                                           write_input):
    res, prompts, _ = run_loop(write_config, write_input, run_tool,
                               ["The total is 2730000."])
    assert res.returncode == 0, res
    assert len(prompts) == 1
    row = res.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["tool_calls"] == []
    assert row["meta"]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Phrase: "If `max_iterations` is reached first, output `null` and use
#          `finish_reason: \"max_iterations\"`."
# Context: Part 4 / Agentic loop, applied to completions mode.
# ---------------------------------------------------------------------------
def test_max_iterations_in_completions_mode(run_tool, write_config,
                                            write_input):
    res, prompts, _ = run_loop(write_config, write_input, run_tool,
                               [LOOKUP_Q1], max_iterations=3)
    assert res.returncode == 0, res
    assert len(prompts) == 3
    row = res.rows[0]
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


# ---------------------------------------------------------------------------
# Phrase: "parse tool calls from response text blocks"
# Context: Part 4 - a block whose JSON does not parse is not a tool call, so
#          the text is the final answer (AMBIGUITIES T86).
# ---------------------------------------------------------------------------
def test_unparseable_block_is_treated_as_final_text(run_tool, write_config,
                                                    write_input):
    broken = "<tool_call>\nnot json at all\n</tool_call>"
    body = text_completion(broken)

    with MockAPI(lambda req, i: (200, body)) as api:
        cfg = write_config(completions_agentic(api.url))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1
    assert res.rows[0]["output"] == {"answer": broken}


# ---------------------------------------------------------------------------
# Phrase: "meta.iterations_detail records per-iteration token usage, latency,
#          and finish reason"
# Context: Part 4 - the same aggregated metadata applies in completions mode.
# ---------------------------------------------------------------------------
def test_completions_agentic_metadata(run_tool, write_config, write_input):
    script = [(LOOKUP_Q1, {"prompt_tokens": 200, "completion_tokens": 30}),
              (FINAL, {"prompt_tokens": 350, "completion_tokens": 40})]
    res, prompts, _ = run_loop(write_config, write_input, run_tool, script)
    assert res.returncode == 0, res
    meta = res.rows[0]["meta"]
    assert meta["total_prompt_tokens"] == 550
    assert meta["total_completion_tokens"] == 70
    assert meta["total_tokens"] == 620
    assert len(meta["iterations_detail"]) == 2
    assert res.summary["total_api_calls"] == 2

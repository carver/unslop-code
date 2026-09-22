"""Checkpoint 4: agentic behaviour in completions mode."""

import json

from conftest import agentic_config
from fake_api import (FakeAPI, agentic, calls, final, text_completion,
                      tool_call_text)


ROW = [{"question": "How many employees?", "answer": "142"}]
CFG = {"api_type": "completions", "chat_template": "chatml"}


def run(run_agentic, script, task=None, rows=None, template="chatml", **kw):
    cfg = dict(CFG)
    cfg["chat_template"] = template
    cfg.update(task or {})
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, task=cfg, rows=rows or ROW, check=0, **kw)
    return res, server


# "tool definitions are rendered into the prompt instead of being sent as a
#  native `tools` field"
def test_tool_definitions_are_rendered_into_the_prompt(run_agentic):
    res, server = run(run_agentic, [final("142")])
    body = server.requests[0].body
    assert "tools" not in body
    prompt = body["prompt"]
    assert "lookup" in prompt and "calculate" in prompt
    assert "Look up a value in the database by key" in prompt
    assert "The math expression to evaluate" in prompt
    assert "<tool_call>" in prompt


def test_rendered_tools_do_not_leak_handler_config(run_agentic):
    res, server = run(run_agentic, [final("142")])
    prompt = server.requests[0].prompt
    assert "static_map" not in prompt
    assert "KEY_NOT_FOUND" not in prompt


def test_tool_definitions_are_rendered_for_every_template(run_agentic):
    for template in ("chatml", "llama3", "mistral", "zephyr"):
        res, server = run(run_agentic, [final("142")], template=template)
        assert "lookup" in server.requests[0].prompt


# "parse tool calls from response text blocks of the form:
#   <tool_call>
#   {"name": "lookup", "arguments": {"key": "revenue_q1"}}
#   </tool_call>"
def test_tool_calls_are_parsed_from_the_response_text(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    res, server = run(run_agentic, script)
    row = res.rows[0]
    assert row["result"]["iterations"] == 2
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"},
         "result": "142"}]
    assert row["output"] == {"answer": "142"}


def test_tool_call_blocks_are_found_inside_surrounding_text(run_agentic):
    def responder(rec):
        if "<|im_start|>tool" not in rec.prompt:
            return 200, text_completion(
                "Let me look that up.\n%s\nchecking..."
                % tool_call_text("lookup", {"key": "employees"}))
        return 200, text_completion("142")
    with FakeAPI(responder) as server:
        res = run_agentic(server, task=CFG, rows=ROW, check=0)
    assert res.rows[0]["result"]["tool_calls"][0]["args"] == {"key": "employees"}
    assert res.rows[0]["output"] == {"answer": "142"}


def test_several_tool_call_blocks_in_one_response(run_agentic):
    script = [calls(("lookup", {"key": "revenue_q1"}),
                    ("lookup", {"key": "revenue_q2"})),
              final("2730000"), final("2730000")]
    res, server = run(run_agentic, script,
                      rows=[{"question": "revenue?", "answer": "2730000"}])
    recorded = res.rows[0]["result"]["tool_calls"]
    assert [c["result"] for c in recorded] == ["1250000", "1480000"]
    assert [c["iteration"] for c in recorded] == [1, 1]


def test_text_without_a_tool_call_block_is_the_final_answer(run_agentic):
    res, server = run(run_agentic, [final("The company has 142 employees.")])
    assert server.call_count == 1
    assert res.rows[0]["output"] == {"answer": "The company has 142 employees."}


# "execute those calls and feed the results back into the next prompt
#  iteration using the template's tool-role formatting"
def test_results_are_fed_back_with_the_chatml_tool_role(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    res, server = run(run_agentic, script)
    second = server.requests[1].prompt
    assert "<|im_start|>tool\n142<|im_end|>\n" in second
    assert second.endswith("<|im_start|>assistant\n")
    # the assistant's own tool-call text stays in the conversation
    assert '"name": "lookup"' in second


def test_results_are_fed_back_with_the_llama3_tool_role(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    res, server = run(run_agentic, script, template="llama3")
    second = server.requests[1].prompt
    assert "<|start_header_id|>tool<|end_header_id|>\n\n142<|eot_id|>" in second
    assert second.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")


def test_results_are_fed_back_with_the_zephyr_tool_role(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    res, server = run(run_agentic, script, template="zephyr")
    second = server.requests[1].prompt
    assert "<|tool|>\n142</s>\n" in second
    assert second.endswith("<|assistant|>\n")


def test_results_are_fed_back_with_the_mistral_tool_role(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    res, server = run(run_agentic, script, template="mistral")
    second = server.requests[1].prompt
    assert "[TOOL_RESULTS] 142 [/TOOL_RESULTS]" in second


def test_the_original_question_survives_every_iteration(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    res, server = run(run_agentic, script)
    assert all(ROW[0]["question"] in r.prompt for r in server.requests)


# The loop's bookkeeping is the same as in chat mode.
def test_max_iterations_in_completions_mode(run_agentic):
    script = [calls(("lookup", {"key": "employees"}))]
    res, server = run(run_agentic, script,
                      task={"generation": {"scheme": "agentic",
                                           "max_iterations": 3,
                                           "temperature": 0.0,
                                           "max_tokens": 512}})
    row = res.rows[0]
    assert server.call_count == 3
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 3


def test_completions_agentic_meta_is_aggregated(run_agentic):
    script = [calls(("lookup", {"key": "employees"}), prompt_tokens=100,
                    completion_tokens=10),
              final("142", prompt_tokens=150, completion_tokens=20)]
    res, server = run(run_agentic, script)
    meta = res.rows[0]["meta"]
    assert meta["total_prompt_tokens"] == 250
    assert meta["total_completion_tokens"] == 30
    assert meta["total_tokens"] == 280
    assert len(meta["iterations_detail"]) == 2
    assert meta["finish_reason"] == "stop"


def test_completions_agentic_body_keys(run_agentic):
    res, server = run(run_agentic, [final("142")])
    assert set(server.requests[0].body) == {"model", "prompt", "temperature",
                                            "max_tokens"}


def test_completions_agentic_with_num_solutions(run_agentic):
    with FakeAPI(agentic([final("142")])) as server:
        task = dict(CFG)
        task["num_solutions"] = 2
        res = run_agentic(server, task=task, rows=ROW, check=0)
    row = res.rows[0]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(row["meta"]) == 2

"""The per-row output an agentic task writes: `result` and `meta`."""

from __future__ import annotations

from conftest import agentic_config, turn_responder
from mock_server import Reply

ROW = [{"question": "How many employees?", "answer": "142"}]
LOOKUP = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
ANSWER = Reply(content="The company has 142 employees.")


def run(servers, run_cli, *replies, rows=ROW, **overrides):
    server = servers(responder=turn_responder(*replies))
    result = run_cli(agentic_config(server.url, **overrides), rows)
    assert result.exit_code == 0, result.stderr
    return result.rows[0]


# Spec: "`result.iterations` is the number of API requests in the loop" -- one
# tool-call request plus the final answer.
def test_iterations_counts_api_requests(servers, run_cli):
    row = run(servers, run_cli, LOOKUP, ANSWER)
    assert row["result"]["iterations"] == 2


# Spec: the single-solution agentic row keeps `attempts`, and one loop is one
# attempt.
def test_attempts_is_one_for_a_single_loop(servers, run_cli):
    row = run(servers, run_cli, LOOKUP, ANSWER)
    assert row["result"]["attempts"] == 1


# Spec: "`result.tool_calls` records every tool call in execution order" and
# "each recorded tool call stores `iteration`, `tool`, parsed `args`, and the
# handler `result`".
def test_tool_calls_are_recorded_in_execution_order(servers, run_cli):
    first = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "revenue_q1"}}])
    second = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "revenue_q2"}}])
    row = run(
        servers,
        run_cli,
        first,
        second,
        Reply(content="Total: 2730000"),
        rows=[{"question": "Total?", "answer": "2730000"}],
    )
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
        {"iteration": 2, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
    ]


# Spec: "`meta.total_*` values are aggregated across all iterations" -- the
# mock reports 45 prompt and 120 completion tokens per request.
def test_meta_totals_are_aggregated(servers, run_cli):
    meta = run(servers, run_cli, LOOKUP, ANSWER)["meta"]
    assert meta["total_prompt_tokens"] == 90
    assert meta["total_completion_tokens"] == 240
    assert meta["total_tokens"] == 330


# Spec: "`meta.iterations_detail` records per-iteration token usage, latency,
# and finish reason".
def test_iterations_detail_has_one_entry_per_request(servers, run_cli):
    detail = run(servers, run_cli, LOOKUP, ANSWER)["meta"]["iterations_detail"]
    assert len(detail) == 2
    assert [entry["finish_reason"] for entry in detail] == ["tool_calls", "stop"]
    assert detail[0]["prompt_tokens"] == 45
    assert detail[0]["completion_tokens"] == 120
    assert detail[0]["total_tokens"] == 165
    assert detail[1]["latency_ms"] >= 0


# Spec: "`meta.latency_ms` is total wall-clock time for the loop" -- so it
# covers both requests, not just the last one. (T65)
def test_latency_covers_the_whole_loop(servers, run_cli):
    server = servers(responder=turn_responder(LOOKUP, ANSWER), service_time=0.2)
    result = run_cli(agentic_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    meta = result.rows[0]["meta"]
    assert meta["latency_ms"] >= 350
    assert meta["latency_ms"] >= sum(item["latency_ms"] for item in meta["iterations_detail"])


# Spec: "`meta.finish_reason` is `\"stop\"` for a final text response".
def test_finish_reason_is_stop_for_a_final_answer(servers, run_cli):
    assert run(servers, run_cli, LOOKUP, ANSWER)["meta"]["finish_reason"] == "stop"


# Spec: "evaluation runs against the final text output only" -- the tool result
# carries a different number than the answer.
def test_evaluation_reads_the_final_text(servers, run_cli):
    lookup = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "revenue_q1"}}])
    row = run(servers, run_cli, lookup, ANSWER)
    assert row["result"]["extracted_answer"] == "142"
    assert row["result"]["passed"] is True


# Spec: "if `max_iterations` is hit, evaluation fails because output is `null`".
def test_max_iterations_row_fails_evaluation(servers, run_cli):
    row = run(servers, run_cli, LOOKUP, generation={"max_iterations": 2})
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"


# Spec: "when evaluation is omitted for a single-solution agentic row, keep the
# part 1 rule: `result.passed` is `null`".
def test_passed_is_null_without_evaluation(servers, run_cli):
    row = run(servers, run_cli, LOOKUP, ANSWER, evaluation=None)
    assert row["result"]["passed"] is None
    assert row["output"] == {"answer": "The company has 142 employees."}


# Spec: the aggregated `meta` object is what the row carries -- the per-request
# metadata lives in `iterations_detail` instead.
def test_meta_is_the_aggregated_object(servers, run_cli):
    meta = run(servers, run_cli, LOOKUP, ANSWER)["meta"]
    assert set(meta) == {
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "iterations_detail",
    }


# Spec: the worked example, whose input answer is "2730000" and whose final
# text is "The total revenue for Q1 and Q2 is $2,730,000." with
# `"passed": true`, `"iterations": 3` and two tool calls on iteration 1. (T4)
def test_spec_example_row(servers, run_cli):
    pair = Reply(
        tool_calls=[
            {"name": "lookup", "arguments": {"key": "revenue_q1"}},
            {"name": "lookup", "arguments": {"key": "revenue_q2"}},
        ]
    )
    row = run(
        servers,
        run_cli,
        pair,
        Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}]),
        Reply(content="The total revenue for Q1 and Q2 is $2,730,000."),
        rows=[{"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"}],
    )
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "2730000"
    assert row["result"]["iterations"] == 3
    assert [call["iteration"] for call in row["result"]["tool_calls"]] == [1, 1, 2]

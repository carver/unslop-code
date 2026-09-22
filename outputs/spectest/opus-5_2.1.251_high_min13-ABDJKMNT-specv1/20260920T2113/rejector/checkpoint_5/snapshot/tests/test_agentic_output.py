"""The per-row output an agentic task writes, in both output formats."""

from __future__ import annotations

from tests.conftest import (
    AGENTIC_ROW, agentic_config, icl_section, lookup_then_answer,
)
from tests.fake_api import calls_ok, ok, tool_call

ANSWER = "The total revenue for Q1 and Q2 is $2,730,000."
AGENTIC_META_KEYS = {
    "total_prompt_tokens", "total_completion_tokens", "total_tokens", "latency_ms",
    "finish_reason", "iterations_detail",
}
ITERATION_KEYS = {
    "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason",
}


def two_step(server_calls: list, final: str = ANSWER):
    """Responder: ask for the listed calls once, then answer with ``final``."""
    def respond(index, body):
        if any(message.get("role") == "tool" for message in body.get("messages", [])):
            return ok(final, prompt_tokens=30, completion_tokens=12)
        return calls_ok(*server_calls, prompt_tokens=20, completion_tokens=8)

    return respond


# The full agentic row shape from the spec's "Agentic Output" example.
def test_row_shape_matches_the_agentic_example(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"}, "call_a"),
                           tool_call("lookup", {"key": "revenue_q2"}, "call_b")]))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert set(row) == {"input", "output", "result", "meta"}
    assert row["input"] == AGENTIC_ROW
    assert row["output"] == {"answer": ANSWER}
    assert row["result"] == {
        "passed": True,
        "extracted_answer": "2730000",
        "attempts": 1,
        "iterations": 2,
        "tool_calls": [
            {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
             "result": "1250000"},
            {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"},
             "result": "1480000"},
        ],
    }


# "result.iterations is the number of API requests in the loop"
def test_iterations_counts_api_requests(cli, api):
    def responder(index, body):
        tools = [m for m in body["messages"] if m["role"] == "tool"]
        if len(tools) >= 2:
            return ok(ANSWER)
        return calls_ok(tool_call("lookup", {"key": "revenue_q1"}, f"call_{index}"))

    server = api(responder)
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["iterations"] == 3
    assert len(server.log.calls) == 3


# "result.tool_calls records every tool call in execution order"
def test_tool_calls_are_recorded_in_execution_order(cli, api):
    def responder(index, body):
        tools = [m for m in body["messages"] if m["role"] == "tool"]
        if len(tools) >= 2:
            return ok(ANSWER)
        key = "revenue_q1" if not tools else "revenue_q2"
        return calls_ok(tool_call("lookup", {"key": key}, f"call_{index}"))

    server = api(responder)
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"},
        {"iteration": 2, "tool": "lookup", "args": {"key": "revenue_q2"},
         "result": "1480000"},
    ]


# "each recorded tool call stores iteration, tool, parsed args, and the handler result"
def test_recorded_tool_call_fields(cli, api):
    server = api(two_step([tool_call("calculate", {"expression": "1250000 + 1480000"})]))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    recorded = run.rows[0]["result"]["tool_calls"][0]
    assert set(recorded) == {"iteration", "tool", "args", "result"}
    assert recorded["tool"] == "calculate"
    assert recorded["args"] == {"expression": "1250000 + 1480000"}
    assert recorded["result"] == '{"expression": "1250000 + 1480000"}'


# "meta.total_* values are aggregated across all iterations"
def test_meta_totals_are_aggregated_over_iterations(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})]))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert set(meta) == AGENTIC_META_KEYS
    assert meta["total_prompt_tokens"] == 50
    assert meta["total_completion_tokens"] == 20
    assert meta["total_tokens"] == 70


# "meta.latency_ms is total wall-clock time for the loop"
def test_meta_latency_covers_the_whole_loop(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})]), delay=0.08)
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert meta["latency_ms"] >= sum(d["latency_ms"] for d in meta["iterations_detail"])
    assert meta["latency_ms"] >= 120


# "meta.iterations_detail records per-iteration token usage, latency, and finish reason"
def test_iterations_detail_has_one_entry_per_request(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})]))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    detail = run.rows[0]["meta"]["iterations_detail"]
    assert [set(entry) for entry in detail] == [ITERATION_KEYS, ITERATION_KEYS]
    assert [entry["finish_reason"] for entry in detail] == ["tool_calls", "stop"]
    assert [entry["prompt_tokens"] for entry in detail] == [20, 30]
    assert [entry["completion_tokens"] for entry in detail] == [8, 12]
    assert [entry["total_tokens"] for entry in detail] == [28, 42]


# 'meta.finish_reason is "stop" for a final text response'
def test_finish_reason_is_stop_for_a_final_answer(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    run = cli.run(agentic_config(api_url=server.url), [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["meta"]["finish_reason"] == "stop"


# 'and "max_iterations" when the iteration limit is hit'
def test_finish_reason_is_max_iterations_at_the_limit(cli, api):
    server = api(lambda index, body: calls_ok(tool_call("lookup", {"key": "employees"})))
    config = agentic_config(api_url=server.url, generation={"max_iterations": 2})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert meta["finish_reason"] == "max_iterations"
    assert [entry["finish_reason"] for entry in meta["iterations_detail"]] == \
        ["tool_calls", "tool_calls"]


# "evaluation runs against the final text output only"
def test_evaluation_ignores_the_tool_results(cli, api):
    # The tool result carries the expected answer; the final text does not.
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})], final="No idea."))
    run = cli.run(agentic_config(api_url=server.url), [{"question": "q", "answer": "1250000"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False
    assert run.rows[0]["result"]["extracted_answer"] is None


# "if max_iterations is hit, evaluation fails because output is null"
def test_max_iterations_fails_evaluation(cli, api):
    server = api(lambda index, body: calls_ok(tool_call("lookup", {"key": "employees"})))
    config = agentic_config(api_url=server.url, generation={"max_iterations": 2})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False
    assert run.rows[0]["result"]["extracted_answer"] is None
    assert run.summary["failed"] == 1


# "when evaluation is omitted for a single-solution agentic row, keep the part 1
#  rule: result.passed is null"
def test_passed_is_null_without_evaluation(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    config = agentic_config(api_url=server.url)
    del config["task"]["evaluation"]
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is None
    assert run.rows[0]["output"] == {"answer": ANSWER}


# "except when max_iterations was reached, where it is false"
def test_passed_is_false_at_the_limit_without_evaluation(cli, api):
    server = api(lambda index, body: calls_ok(tool_call("lookup", {"key": "employees"})))
    config = agentic_config(api_url=server.url, generation={"max_iterations": 2})
    del config["task"]["evaluation"]
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


# "if num_solutions: 2 and both loops produce a final answer on their first API
#  request ... result.passed is 2, result.failed is 0, result.attempts is 2"
def test_num_solutions_uses_the_list_format(cli, static_api):
    server = static_api(ANSWER)
    config = agentic_config(api_url=server.url, num_solutions=2,
                            generation={"temperature": 0.7})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == [
        {"answer": ANSWER, "icl_setup": None}, {"answer": ANSWER, "icl_setup": None},
    ]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(server.log.calls) == 2


# "meta is a list with two entries, one aggregated agentic metadata object per loop"
def test_list_format_meta_is_one_aggregated_object_per_loop(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})]))
    config = agentic_config(api_url=server.url, num_solutions=2,
                            generation={"temperature": 0.7})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert len(meta) == 2
    assert set(meta[0]) == AGENTIC_META_KEYS | {"icl_setup", "evaluation_passed"}
    assert meta[0]["evaluation_passed"] is True
    assert meta[0]["total_tokens"] == 70
    assert len(meta[0]["iterations_detail"]) == 2


# "each solution is an independent loop" - four requests for two two-step loops.
def test_each_solution_runs_its_own_loop(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})]))
    config = agentic_config(api_url=server.url, num_solutions=2,
                            generation={"temperature": 0.7})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 4
    assert run.summary["total_api_calls"] == 4


# "agentic also works with ICL" - demonstrations precede the row's own message.
def test_icl_examples_open_the_conversation(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", ANSWER))
    config = agentic_config(api_url=server.url, icl=icl_section("cot"))
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    roles = [message["role"] for message in server.log.bodies[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert run.rows[0]["meta"][0]["icl_setup"] == "cot"


# "in that list format, result.attempts is the number of loops started for the
#  row, not the number of API requests across those loops"
def test_list_attempts_counts_loops_not_requests(cli, api):
    server = api(two_step([tool_call("lookup", {"key": "revenue_q1"})]))
    config = agentic_config(api_url=server.url, num_solutions=3,
                            generation={"temperature": 0.7})
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 3
    assert len(server.log.calls) == 6


# "when evaluation is omitted in the checkpoint 3 list format ... result.passed
#  is the number of emitted outputs, result.failed is the number of loops that
#  produced no output, and each metadata entry sets evaluation_passed to null"
def test_list_format_without_evaluation_counts_outputs(cli, api):
    def responder(index, body):
        if index == 0:
            return ok(ANSWER)
        return calls_ok(tool_call("lookup", {"key": "employees"}))

    server = api(responder)
    config = agentic_config(api_url=server.url, num_solutions=2,
                            generation={"temperature": 0.7, "max_iterations": 2})
    del config["task"]["evaluation"]
    run = cli.run(config, [AGENTIC_ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert len(row["output"]) == 1
    assert row["result"] == {"passed": 1, "failed": 1, "attempts": 2}
    assert [entry["evaluation_passed"] for entry in row["meta"]] == [None, None]
    assert [entry["finish_reason"] for entry in row["meta"]] == ["stop", "max_iterations"]


# The list format keeps checkpoint 3's summary columns for agentic tasks too.
def test_summary_counts_agentic_solutions(cli, static_api):
    server = static_api(ANSWER)
    task = agentic_config(api_url=server.url, num_solutions=2,
                          generation={"temperature": 0.7})["task"]
    run = cli.run_multi({"defaults": {}, "tasks": {"data_lookup": task}},
                        {"data_lookup": [AGENTIC_ROW]})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["data_lookup"]["total_solutions"] == 2

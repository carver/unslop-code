"""The per-row document an agentic task writes, single and list format."""

from __future__ import annotations

from conftest import agentic_config, icl_setup
from fake_server import FakeAPIServer, conversation

ROW = {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"}
ANSWER = "The total revenue for Q1 and Q2 is $2,730,000."
LOOKUPS = [("lookup", {"key": "revenue_q1"}), ("lookup", {"key": "revenue_q2"})]


def _run(write_config, write_input, run_cli, config_map, *extra, responder=None, rows=None):
    with FakeAPIServer(responder or conversation([LOOKUPS, ANSWER])) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
    return result


# Spec: the agentic per-row example - `input`, `output`, `result`, `meta`
def test_row_keeps_the_part_one_document_shape(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    row = result.rows[0]
    assert list(row) == ["input", "output", "result", "meta"]
    assert row["input"] == ROW
    assert row["output"] == {"answer": ANSWER}


# Spec: "result.iterations is the number of API requests in the loop"
def test_iterations_counts_api_requests(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config(""),
        responder=conversation([LOOKUPS, [("lookup", {"key": "employees"})], ANSWER]),
    )

    assert result.rows[0]["result"]["iterations"] == 3
    assert len(result.payloads) == 3


# Spec: "if the model calls lookup(key="employees") ... then a final response
# ... result.iterations is 2 and result.tool_calls contains the lookup"
def test_single_lookup_then_answer_reports_two_iterations(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config(""),
        responder=conversation([[("lookup", {"key": "employees"})], "The company has 142 employees."]),
    )

    row = result.rows[0]
    assert row["result"]["iterations"] == 2
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"}, "result": "142"}
    ]


# Spec: "each recorded tool call stores `iteration`, `tool`, parsed `args`,
# and the handler `result`"
def test_tool_call_records_carry_the_documented_keys(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    for call in result.rows[0]["result"]["tool_calls"]:
        assert list(call) == ["iteration", "tool", "args", "result"]


# Spec: "result.tool_calls records every tool call in execution order"
def test_tool_calls_are_recorded_in_execution_order(write_config, write_input, run_cli):
    script = [LOOKUPS, [("lookup", {"key": "employees"})], ANSWER]
    result = _run(write_config, write_input, run_cli, agentic_config(""), responder=conversation(script))

    calls = result.rows[0]["result"]["tool_calls"]
    assert [call["args"]["key"] for call in calls] == ["revenue_q1", "revenue_q2", "employees"]
    assert [call["iteration"] for call in calls] == [1, 1, 2]


# Spec: the example row's `result` - "passed", "extracted_answer",
# "attempts": 1 for one loop
def test_result_reports_one_attempt_for_a_single_loop(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert result.rows[0]["result"]["attempts"] == 1
    assert result.rows[0]["result"]["passed"] is True
    assert result.rows[0]["result"]["extracted_answer"] == "2730000"


# Spec: "meta.total_* values are aggregated across all iterations"
def test_meta_totals_are_aggregated_over_iterations(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    meta = result.rows[0]["meta"]
    detail = meta["iterations_detail"]
    assert meta["total_prompt_tokens"] == sum(entry["prompt_tokens"] for entry in detail)
    assert meta["total_completion_tokens"] == sum(entry["completion_tokens"] for entry in detail)
    assert meta["total_tokens"] == sum(entry["total_tokens"] for entry in detail)


# Spec: "meta.iterations_detail records per-iteration token usage, latency,
# and finish reason"
def test_iterations_detail_has_one_entry_per_request(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    detail = result.rows[0]["meta"]["iterations_detail"]
    assert len(detail) == 2
    assert list(detail[0]) == [
        "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason"
    ]
    assert detail[0]["finish_reason"] == "tool_calls"
    assert detail[1]["finish_reason"] == "stop"


# Spec: "meta.latency_ms is total wall-clock time for the loop"
def test_meta_latency_covers_the_whole_loop(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    meta = result.rows[0]["meta"]
    assert meta["latency_ms"] >= sum(entry["latency_ms"] for entry in meta["iterations_detail"])


# Spec: "meta.finish_reason is "stop" for a final text response"
def test_meta_finish_reason_is_stop_for_a_final_answer(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, agentic_config(""))

    assert result.rows[0]["meta"]["finish_reason"] == "stop"


# Spec: "meta.finish_reason is ... "max_iterations" when the iteration limit
# is hit" and "write output: null"
def test_max_iterations_row_reports_null_output_and_the_reason(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config("", max_iterations=2),
        responder=conversation([LOOKUPS]),
    )

    row = result.rows[0]
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 2


# Spec: "if max_iterations is hit, evaluation fails because output is null"
def test_max_iterations_row_fails_evaluation(write_config, write_input, run_cli):
    result = _run(
        write_config, write_input, run_cli, agentic_config("", max_iterations=1),
        responder=conversation([LOOKUPS]),
    )

    assert result.rows[0]["result"]["passed"] is False
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "when evaluation is omitted for a single-solution agentic row, keep
# the part 1 rule: result.passed is null"
def test_passed_is_null_without_evaluation(write_config, write_input, run_cli):
    config_map = agentic_config("")
    del config_map["task"]["evaluation"]
    result = _run(write_config, write_input, run_cli, config_map)

    assert result.rows[0]["result"]["passed"] is None
    assert result.rows[0]["output"] == {"answer": ANSWER}


# Spec: "agentic also works with ICL and num_solutions; each solution is an
# independent loop"
def test_num_solutions_runs_one_loop_per_solution(write_config, write_input, run_cli):
    config_map = agentic_config("", num_solutions=2)
    result = _run(write_config, write_input, run_cli, config_map)

    assert len(result.payloads) == 4
    assert len(result.rows[0]["output"]) == 2


# Spec: "if num_solutions: 2 and both loops produce a final answer on their
# first API request ... result.passed is 2, result.failed is 0, and
# result.attempts is 2"
def test_list_format_counts_loops_not_requests(write_config, write_input, run_cli):
    config_map = agentic_config("", num_solutions=2)
    result = _run(
        write_config, write_input, run_cli, config_map, responder=conversation([ANSWER])
    )

    assert result.rows[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(result.payloads) == 2


# Spec: "output follows the checkpoint 3 list format with two items"
def test_list_format_output_items_keep_the_icl_setup_key(write_config, write_input, run_cli):
    config_map = agentic_config("", num_solutions=2)
    result = _run(
        write_config, write_input, run_cli, config_map, responder=conversation([ANSWER])
    )

    assert result.rows[0]["output"] == [
        {"answer": ANSWER, "icl_setup": None},
        {"answer": ANSWER, "icl_setup": None},
    ]


# Spec: "meta is a list with two entries, one aggregated agentic metadata
# object per loop"
def test_list_format_meta_is_one_entry_per_loop(write_config, write_input, run_cli):
    config_map = agentic_config("", num_solutions=2)
    result = _run(write_config, write_input, run_cli, config_map)

    metas = result.rows[0]["meta"]
    assert len(metas) == 2
    assert all(len(meta["iterations_detail"]) == 2 for meta in metas)


# Spec: "per-loop agentic metadata lives in each meta entry: keep checkpoint
# 3's icl_setup / evaluation_passed fields and also record that loop's
# aggregated total_prompt_tokens, total_completion_tokens, total_tokens,
# latency_ms, finish_reason, and iterations_detail"
def test_list_format_meta_entry_fields(write_config, write_input, run_cli):
    config_map = agentic_config("")
    config_map["task"]["icl"] = {"setups": [icl_setup("demo", "demo answer")]}
    result = _run(write_config, write_input, run_cli, config_map)

    assert set(result.rows[0]["meta"][0]) == {
        "icl_setup",
        "evaluation_passed",
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "iterations_detail",
    }
    assert result.rows[0]["meta"][0]["icl_setup"] == "demo"
    assert result.rows[0]["meta"][0]["evaluation_passed"] is True


# Spec: "when evaluation is omitted in the checkpoint 3 list format ...
# result.passed is the number of emitted outputs, result.failed is the number
# of loops that produced no output, and each metadata entry sets
# evaluation_passed to null"
def test_list_format_without_evaluation_counts_emitted_outputs(write_config, write_input, run_cli):
    config_map = agentic_config("", num_solutions=2)
    del config_map["task"]["evaluation"]
    result = _run(
        write_config, write_input, run_cli, config_map, responder=conversation([ANSWER])
    )

    assert result.rows[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert all(meta["evaluation_passed"] is None for meta in result.rows[0]["meta"])


# Spec: "result.failed is the number of loops that produced no output" - a
# loop that exhausts max_iterations emits nothing
def test_list_format_counts_a_max_iteration_loop_as_failed(write_config, write_input, run_cli):
    config_map = agentic_config("", num_solutions=2, max_iterations=1)
    del config_map["task"]["evaluation"]
    result = _run(
        write_config, write_input, run_cli, config_map, responder=conversation([LOOKUPS])
    )

    assert result.rows[0]["output"] == []
    assert result.rows[0]["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert all(meta["finish_reason"] == "max_iterations" for meta in result.rows[0]["meta"])

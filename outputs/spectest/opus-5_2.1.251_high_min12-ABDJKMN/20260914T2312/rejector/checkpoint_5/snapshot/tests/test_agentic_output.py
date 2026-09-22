"""Checkpoint 4 per-row output for an agentic task."""

import json

from fake_api import FakeAPI, agentic, calls, final, Step


ROW = [{"question": "What is the total revenue for Q1 and Q2?",
        "answer": "2730000"}]

# The spec's worked example: two lookups on iteration 1, then a final answer.
SPEC_SCRIPT = [
    calls(("lookup", {"key": "revenue_q1"}), ("lookup", {"key": "revenue_q2"}),
          prompt_tokens=200, completion_tokens=30),
    calls(("calculate", {"expression": "1250000 + 1480000"}),
          prompt_tokens=350, completion_tokens=40),
    final("The total revenue is 2730000", prompt_tokens=300,
          completion_tokens=50),
]


def spec_run(run_agentic, **kw):
    with FakeAPI(agentic(SPEC_SCRIPT)) as server:
        res = run_agentic(server, rows=ROW, check=0, **kw)
    return res.rows[0]


# "output": {"answer": "..."} -- the final text under `output_field`
def test_output_holds_the_final_text_under_the_output_field(run_agentic):
    row = spec_run(run_agentic)
    assert row["output"] == {"answer": "The total revenue is 2730000"}
    assert row["input"] == ROW[0]


# "`result.iterations` is the number of API requests in the loop"
def test_result_iterations_counts_api_requests(run_agentic):
    assert spec_run(run_agentic)["result"]["iterations"] == 3


# "result": {"passed": true, "extracted_answer": "2730000", "attempts": 1, ...}
def test_result_fields_for_a_single_agentic_row(run_agentic):
    result = spec_run(run_agentic)["result"]
    assert result["passed"] is True
    assert result["extracted_answer"] == "2730000"
    assert result["attempts"] == 1


# "`result.tool_calls` records every tool call in execution order"
# "each recorded tool call stores `iteration`, `tool`, parsed `args`, and the
#  handler `result`"
def test_tool_calls_are_recorded_in_execution_order(run_agentic):
    recorded = spec_run(run_agentic)["result"]["tool_calls"]
    assert [c["tool"] for c in recorded] == ["lookup", "lookup", "calculate"]
    assert [c["iteration"] for c in recorded] == [1, 1, 2]
    assert recorded[0] == {"iteration": 1, "tool": "lookup",
                           "args": {"key": "revenue_q1"},
                           "result": "1250000"}
    assert recorded[1]["result"] == "1480000"
    assert json.loads(recorded[2]["result"]) == \
        {"expression": "1250000 + 1480000"}


def test_tool_calls_is_empty_when_no_tool_was_used(run_agentic):
    with FakeAPI(agentic([final("2730000")])) as server:
        res = run_agentic(server, rows=ROW, check=0)
    assert res.rows[0]["result"]["tool_calls"] == []
    assert res.rows[0]["result"]["iterations"] == 1


# "`meta.total_*` values are aggregated across all iterations"
def test_meta_totals_are_aggregated(run_agentic):
    meta = spec_run(run_agentic)["meta"]
    assert meta["total_prompt_tokens"] == 200 + 350 + 300
    assert meta["total_completion_tokens"] == 30 + 40 + 50
    assert meta["total_tokens"] == 850 + 120


# "`meta.iterations_detail` records per-iteration token usage, latency, and
#  finish reason"
def test_iterations_detail_has_one_entry_per_request(run_agentic):
    detail = spec_run(run_agentic)["meta"]["iterations_detail"]
    assert len(detail) == 3
    assert [d["prompt_tokens"] for d in detail] == [200, 350, 300]
    assert [d["completion_tokens"] for d in detail] == [30, 40, 50]
    assert [d["total_tokens"] for d in detail] == [230, 390, 350]
    assert [d["finish_reason"] for d in detail] == ["tool_calls", "tool_calls",
                                                    "stop"]
    assert all(isinstance(d["latency_ms"], int) for d in detail)


# "`meta.latency_ms` is total wall-clock time for the loop"
def test_meta_latency_covers_the_whole_loop(run_agentic):
    with FakeAPI(agentic(SPEC_SCRIPT), latency=0.05) as server:
        res = run_agentic(server, rows=ROW, check=0)
    meta = res.rows[0]["meta"]
    assert meta["latency_ms"] >= 150
    assert meta["latency_ms"] >= sum(d["latency_ms"]
                                     for d in meta["iterations_detail"])


# "`meta.finish_reason` is `"stop"` for a final text response"
def test_meta_finish_reason_is_stop(run_agentic):
    assert spec_run(run_agentic)["meta"]["finish_reason"] == "stop"


# The aggregated agentic meta replaces the per-attempt object of earlier parts.
def test_agentic_meta_keys(run_agentic):
    meta = spec_run(run_agentic)["meta"]
    assert set(meta) == {"total_prompt_tokens", "total_completion_tokens",
                         "total_tokens", "latency_ms", "finish_reason",
                         "iterations_detail"}


# "evaluation runs against the final text output only"
def test_evaluation_ignores_tool_results(run_agentic):
    # The tool returns 142 but the final text says 999: the row must fail.
    script = [calls(("lookup", {"key": "employees"})), final("the answer: 999")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=[{"question": "q", "answer": "142"}],
                          check=0)
    row = res.rows[0]
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] == "999"


# "if `max_iterations` is hit, evaluation fails because output is `null`"
def test_max_iterations_row_fails_evaluation(run_agentic):
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"}))])) as server:
        res = run_agentic(server,
                          task={"generation": {"scheme": "agentic",
                                               "max_iterations": 2,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert res.summary["failed"] == 1 and res.summary["passed"] == 0


def test_max_iterations_still_records_the_tool_calls(run_agentic):
    with FakeAPI(agentic([calls(("lookup", {"key": "employees"}))])) as server:
        res = run_agentic(server,
                          task={"generation": {"scheme": "agentic",
                                               "max_iterations": 2,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=[{"question": "q", "answer": "142"}], check=0)
    result = res.rows[0]["result"]
    assert result["iterations"] == 2
    assert [c["iteration"] for c in result["tool_calls"]] == [1, 2]
    assert len(res.rows[0]["meta"]["iterations_detail"]) == 2


# "when evaluation is omitted for a single-solution agentic row, keep the part
#  1 rule: `result.passed` is `null`"
def test_no_evaluation_single_row_passed_is_null(run_agentic):
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, task={"evaluation": None},
                          rows=[{"question": "q"}], check=0)
    row = res.rows[0]
    assert row["result"]["passed"] is None
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["iterations"] == 2
    assert row["output"] == {"answer": "142"}


# The summary still counts agentic rows the usual way.
def test_summary_counts_agentic_rows(run_agentic):
    rows = [{"question": "q1", "answer": "142"},
            {"question": "q2", "answer": "999"}]
    script = [calls(("lookup", {"key": "employees"})), final("142")]
    with FakeAPI(agentic(script)) as server:
        res = run_agentic(server, rows=rows, check=0)
    summary = res.summary
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["total_prompt_tokens"] == 4 * 45
    assert summary["total_completion_tokens"] == 4 * 120

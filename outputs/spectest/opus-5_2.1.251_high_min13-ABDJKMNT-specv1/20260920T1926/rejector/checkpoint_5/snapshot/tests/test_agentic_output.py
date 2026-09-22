"""The per-row record an agentic task writes, and the totals it aggregates."""

from __future__ import annotations

from conftest import agentic_task
from fake_api import FakeAPI, Reply, always, call, turns

TOTALS = {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"}

# The spec's worked example: one iteration with two lookups, then the answer.
LOOKUPS = Reply(
    content=None,
    tools=(call("lookup", key="revenue_q1"), call("lookup", key="revenue_q2")),
    prompt_tokens=200,
    completion_tokens=30,
)
CALCULATION = Reply(
    content=None,
    tools=(call("calculate", expression="1250000 + 1480000"),),
    prompt_tokens=350,
    completion_tokens=40,
)
ANSWER = Reply(
    content="The total revenue for Q1 and Q2 is $2,730,000.",
    prompt_tokens=300,
    completion_tokens=50,
)


def spec_example(write_config, write_input, run_cli) -> dict:
    with FakeAPI(responder=turns([LOOKUPS, CALCULATION, ANSWER])) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([TOTALS]))
    return result.rows[0]


# Spec: the `input` / `output` keys of the agentic output example.
# Context: Agentic Output.
def test_input_and_output_follow_the_example(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    assert row["input"] == TOTALS
    assert row["output"] == {"answer": "The total revenue for Q1 and Q2 is $2,730,000."}


# Spec: "`result.iterations` is the number of API requests in the loop"
# Context: Agentic Output / Rules.
def test_iterations_counts_the_api_requests(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    assert row["result"]["iterations"] == 3
    assert row["result"]["attempts"] == 1


# Spec: "`result.tool_calls` records every tool call in execution order" /
# "each recorded tool call stores `iteration`, `tool`, parsed `args`, and the
# handler `result`"
# Context: Agentic Output / Rules.
def test_tool_calls_are_recorded_in_execution_order(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
        {
            "iteration": 2,
            "tool": "calculate",
            "args": {"expression": "1250000 + 1480000"},
            "result": '{"expression": "1250000 + 1480000"}',
        },
    ]


# Spec: "evaluation runs against the final text output only"
# Context: Agentic Output / Rules. Part 1's `last_number` is unchanged, so the
# grouped "$2,730,000." extracts as "000"; see AMBIGUITIES T50.
def test_evaluation_runs_against_the_final_text(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    assert row["result"]["extracted_answer"] == "000"
    assert row["result"]["passed"] is False


# Spec: "`meta.total_*` values are aggregated across all iterations"
# Context: Agentic Output / Rules.
def test_meta_totals_are_aggregated(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    assert row["meta"]["total_prompt_tokens"] == 850
    assert row["meta"]["total_completion_tokens"] == 120
    assert row["meta"]["total_tokens"] == 970


# Spec: "`meta.iterations_detail` records per-iteration token usage, latency,
# and finish reason"
# Context: Agentic Output / Rules.
def test_iterations_detail_has_one_entry_per_iteration(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    detail = row["meta"]["iterations_detail"]
    assert len(detail) == 3
    assert [entry["prompt_tokens"] for entry in detail] == [200, 350, 300]
    assert [entry["completion_tokens"] for entry in detail] == [30, 40, 50]
    assert [entry["total_tokens"] for entry in detail] == [230, 390, 350]
    assert [entry["finish_reason"] for entry in detail] == ["tool_calls", "tool_calls", "stop"]
    assert all(isinstance(entry["latency_ms"], int) for entry in detail)
    assert set(detail[0]) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
    }


# Spec: "`meta.latency_ms` is total wall-clock time for the loop"
# Context: Agentic Output / Rules.
def test_meta_latency_covers_the_whole_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUPS, CALCULATION, ANSWER]), delay=0.1) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([TOTALS]))
    meta = result.rows[0]["meta"]
    detail = meta["iterations_detail"]
    # Iterations run back to back, so the loop spans their sum; each figure is
    # rounded to whole milliseconds on its own, hence one millisecond of slack
    # per iteration.
    assert meta["latency_ms"] >= sum(entry["latency_ms"] for entry in detail) - len(detail)


# Spec: "`meta.finish_reason` is `\"stop\"` for a final text response"
# Context: Agentic Output / Rules.
def test_meta_carries_only_the_aggregated_keys(write_config, write_input, run_cli):
    row = spec_example(write_config, write_input, run_cli)
    assert set(row["meta"]) == {
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "iterations_detail",
    }
    assert row["meta"]["finish_reason"] == "stop"


# Spec: "when evaluation is omitted for a single-solution agentic row, keep
# the part 1 rule: `result.passed` is `null`"
# Context: Agentic Output / Rules.
def test_without_evaluation_passed_is_null(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUPS, ANSWER])) as api:
        task = agentic_task(api.url)
        del task["evaluation"]
        result = run_cli(write_config(task), write_input([TOTALS]))
    assert result.rows[0]["result"]["passed"] is None
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: "except when `max_iterations` was reached, where it is `false`"
# Context: Agentic Output / Rules.
def test_without_evaluation_max_iterations_is_false(write_config, write_input, run_cli):
    with FakeAPI(responder=always(None, tools=(call("lookup", key="employees"),))) as api:
        task = agentic_task(api.url)
        del task["evaluation"]
        task["generation"]["max_iterations"] = 2
        result = run_cli(write_config(task), write_input([TOTALS]))
    row = result.rows[0]
    assert row["result"]["passed"] is False
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert len(row["meta"]["iterations_detail"]) == 2


# Spec: "`meta.total_*` values are aggregated across all iterations"
# Context: Agentic Output; the run summary counts the same tokens.
def test_summary_totals_include_every_iteration(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUPS, CALCULATION, ANSWER])) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([TOTALS]))
    assert result.summary["total_prompt_tokens"] == 850
    assert result.summary["total_completion_tokens"] == 120
    assert result.summary["total_api_calls"] == 3

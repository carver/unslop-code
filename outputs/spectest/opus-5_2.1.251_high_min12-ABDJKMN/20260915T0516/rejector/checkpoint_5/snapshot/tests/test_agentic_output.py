"""Part 4: the per-row output record for an agentic task."""
import pytest

from conftest import agentic_config, icl_block, marker_setups, static_map_tool
from mock_api import MockAPI, agentic_turns, always

ROWS = [{"question": "What is the total revenue for Q1 and Q2?",
         "answer": "2730000"}]
EMPLOYEES = [{"question": "How many employees are there?", "answer": "142"}]

RESULT_KEYS = {"passed", "extracted_answer", "attempts", "iterations",
               "tool_calls"}
META_KEYS = {"total_prompt_tokens", "total_completion_tokens", "total_tokens",
             "latency_ms", "finish_reason", "iterations_detail"}
DETAIL_KEYS = {"prompt_tokens", "completion_tokens", "total_tokens",
               "latency_ms", "finish_reason"}

SPEC_STEPS = [[("lookup", {"key": "revenue_q1"}),
               ("lookup", {"key": "revenue_q2"})],
              [("calculate", {"expression": "1250000 + 1480000"})],
              "The total revenue for Q1 and Q2 is $2,730,000."]


def spec_run(run_tool, steps=None, rows=None, **kw):
    with MockAPI(agentic_turns(steps or SPEC_STEPS)) as api:
        run = run_tool(agentic_config(api.url, **kw), rows or ROWS)
    assert run.returncode == 0, run.stderr
    return run


# Spec: the Agentic Output example — `input`, `output`, `result`, `meta`.
# Context: Agentic Output.
def test_row_has_the_four_top_level_keys(run_tool):
    row = spec_run(run_tool).rows[0]
    assert list(row) == ["input", "output", "result", "meta"]
    assert row["input"] == ROWS[0]
    assert row["output"] == {"answer": "The total revenue for Q1 and Q2 is "
                                       "$2,730,000."}


def test_result_carries_the_agentic_keys(run_tool):
    row = spec_run(run_tool).rows[0]
    assert set(row["result"]) == RESULT_KEYS
    assert row["result"]["passed"] is True
    assert row["result"]["extracted_answer"] == "2730000"
    assert row["result"]["attempts"] == 1


# Spec: the example output pairs
#       `"answer": "The total revenue for Q1 and Q2 is $2,730,000."` with
#       `"extracted_answer": "2730000"` and `"passed": true`, so
#       `last_number` reads thousands separators as part of the number.
# Context: Agentic Output example (resolves AMBIGUITIES.md T10).
def test_last_number_reads_through_thousands_separators(run_tool):
    row = spec_run(run_tool).rows[0]
    assert row["output"]["answer"].endswith("$2,730,000.")
    assert row["result"]["extracted_answer"] == "2730000"
    assert row["result"]["passed"] is True


# Spec: "`result.iterations` is the number of API requests in the loop"
# Context: Agentic Output rules.
def test_iterations_counts_api_requests(run_tool):
    row = spec_run(run_tool).rows[0]
    assert row["result"]["iterations"] == 3


# Spec: "`result.iterations` is `2` and `result.tool_calls` contains the
#        lookup" (one lookup, then the final answer)
# Context: Examples, Simple lookup.
def test_simple_lookup_example(run_tool):
    steps = [[("lookup", {"key": "employees"})], "The company has 142 employees."]
    run = spec_run(run_tool, steps, EMPLOYEES)
    row = run.rows[0]
    assert row["result"]["iterations"] == 2
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"},
         "result": "142"}]
    assert row["result"]["passed"] is True


# Spec: "`result.tool_calls` records every tool call in execution order" /
#       "each recorded tool call stores `iteration`, `tool`, parsed `args`,
#        and the handler `result`"
# Context: Agentic Output rules.
def test_tool_calls_record_iteration_tool_args_and_result(run_tool):
    row = spec_run(run_tool).rows[0]
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"},
         "result": "1480000"},
        {"iteration": 2, "tool": "calculate",
         "args": {"expression": "1250000 + 1480000"},
         "result": '{"expression": "1250000 + 1480000"}'},
    ]


def test_tool_calls_is_empty_when_no_tool_was_called(run_tool):
    with MockAPI(always("2730000")) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["tool_calls"] == []
    assert run.rows[0]["result"]["iterations"] == 1


# Spec: "`meta.total_*` values are aggregated across all iterations"
# Context: Agentic Output rules.
def test_meta_totals_are_aggregated_across_iterations(run_tool):
    meta = spec_run(run_tool).rows[0]["meta"]
    assert set(meta) == META_KEYS
    assert meta["total_prompt_tokens"] == 3 * 45
    assert meta["total_completion_tokens"] == 3 * 120
    assert meta["total_tokens"] == 3 * 165


# Spec: "`meta.iterations_detail` records per-iteration token usage, latency,
#        and finish reason"
# Context: Agentic Output rules.
def test_iterations_detail_has_one_entry_per_request(run_tool):
    meta = spec_run(run_tool).rows[0]["meta"]
    detail = meta["iterations_detail"]
    assert len(detail) == 3
    assert all(set(entry) == DETAIL_KEYS for entry in detail)
    assert [e["finish_reason"] for e in detail] == ["tool_calls", "tool_calls",
                                                    "stop"]
    assert detail[0]["prompt_tokens"] == 45
    assert detail[0]["completion_tokens"] == 120
    assert detail[0]["total_tokens"] == 165


# Spec: "`meta.latency_ms` is total wall-clock time for the loop"
# Context: Agentic Output rules.
def test_latency_is_the_whole_loop(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    with MockAPI(agentic_turns(steps), service_seconds=0.15) as api:
        run = run_tool(agentic_config(api.url), EMPLOYEES)
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    per_iteration = sum(e["latency_ms"] for e in meta["iterations_detail"])
    assert meta["latency_ms"] >= per_iteration
    assert meta["latency_ms"] >= 300


# Spec: "`meta.finish_reason` is `"stop"` for a final text response"
# Context: Agentic Output rules.
def test_finish_reason_is_stop_for_a_final_text_response(run_tool):
    assert spec_run(run_tool).rows[0]["meta"]["finish_reason"] == "stop"


# Spec: "`meta.finish_reason` is ... `"max_iterations"` when the iteration
#        limit is hit" / "write `output: null`"
# Context: Agentic Output rules / Examples, Max-iteration failure.
def test_max_iterations_row(run_tool):
    steps = [[("lookup", {"key": "employees"})]]
    run = spec_run(run_tool, steps, EMPLOYEES, max_iterations=4)
    row = run.rows[0]
    assert row["output"] is None
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["result"]["iterations"] == 4
    assert len(row["meta"]["iterations_detail"]) == 4


# Spec: "evaluation runs against the final text output only" /
#       "if `max_iterations` is hit, evaluation fails because output is `null`"
# Context: Agentic Output rules.
def test_evaluation_ignores_tool_results(run_tool):
    # The tool results contain the expected answer; the final text does not.
    steps = [[("lookup", {"key": "revenue_q1"})], "I could not work it out."]
    run = spec_run(run_tool, steps, [{"question": "q", "answer": "1250000"}])
    row = run.rows[0]
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None


def test_max_iterations_fails_evaluation(run_tool):
    steps = [[("lookup", {"key": "employees"})]]
    row = spec_run(run_tool, steps, EMPLOYEES, max_iterations=2).rows[0]
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["tool_calls"][0]["iteration"] == 1
    assert row["result"]["tool_calls"][-1]["iteration"] == 2


def test_max_iterations_row_counts_as_failed_in_the_summary(run_tool):
    steps = [[("lookup", {"key": "employees"})]]
    run = spec_run(run_tool, steps, EMPLOYEES, max_iterations=2)
    assert run.summary["passed"] == 0
    assert run.summary["failed"] == 1
    assert run.summary["total_api_calls"] == 2


# Spec: "when evaluation is omitted for a single-solution agentic row, keep
#        the part 1 rule: `result.passed` is `null`"
# Context: Agentic Output rules.
def test_passed_is_null_without_evaluation(run_tool):
    row = spec_run(run_tool, evaluation=None).rows[0]
    assert row["result"]["passed"] is None
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["iterations"] == 3


# ------------------------------------------------- the list output format ---

# Spec: "`agentic` also works with ICL and `num_solutions`; each solution is
#        an independent loop" / "when ICL is configured or
#        `num_solutions > 1`, keep the checkpoint 3 list output format"
# Context: Agentic Output rules / Examples, Agentic list-format run.
def test_num_solutions_two_emits_two_output_items(run_tool):
    steps = ["The answer is 2730000."]
    run = spec_run(run_tool, steps, num_solutions=2)
    row = run.rows[0]
    assert row["output"] == [{"answer": "The answer is 2730000.",
                              "icl_setup": None},
                             {"answer": "The answer is 2730000.",
                              "icl_setup": None}]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(row["meta"]) == 2


# Spec: "in that list format, `result.attempts` is the number of loops
#        started for the row, not the number of API requests across those
#        loops"
# Context: Agentic Output rules.
def test_attempts_counts_loops_not_requests(run_tool):
    run = spec_run(run_tool, num_solutions=2)     # 3 requests per loop
    assert run.rows[0]["result"]["attempts"] == 2
    assert run.summary["total_api_calls"] == 6


# Spec: "per-loop agentic metadata lives in each `meta` entry: keep
#        checkpoint 3's `icl_setup` / `evaluation_passed` fields and also
#        record that loop's aggregated `total_prompt_tokens`,
#        `total_completion_tokens`, `total_tokens`, `latency_ms`,
#        `finish_reason`, and `iterations_detail`"
# Context: Agentic Output rules.
def test_meta_entries_carry_aggregated_agentic_metadata(run_tool):
    run = spec_run(run_tool, num_solutions=2)
    entry = run.rows[0]["meta"][0]
    assert META_KEYS <= set(entry)
    assert {"icl_setup", "evaluation_passed"} <= set(entry)
    assert entry["total_prompt_tokens"] == 3 * 45
    assert entry["total_completion_tokens"] == 3 * 120
    assert entry["total_tokens"] == 3 * 165
    assert entry["finish_reason"] == "stop"
    assert len(entry["iterations_detail"]) == 3
    assert entry["evaluation_passed"] is True
    assert entry["icl_setup"] is None


def test_meta_entries_record_the_icl_setup_of_their_loop(run_tool):
    icl = icl_block(marker_setups(["A", "B"]), strategy="round_robin")
    run = spec_run(run_tool, ["2730000"], num_solutions=2, icl=icl)
    row = run.rows[0]
    assert [m["icl_setup"] for m in row["meta"]] == ["A", "B"]
    assert [o["icl_setup"] for o in row["output"]] == ["A", "B"]


# Spec: "if `num_solutions: 2` and both loops produce a final answer on their
#        first API request ... `result.passed` is `2`, `result.failed` is
#        `0`, and `result.attempts` is `2` ... `meta` is a list with two
#        entries, one aggregated agentic metadata object per loop"
# Context: Examples, Agentic list-format run.
def test_agentic_list_format_example(run_tool):
    steps = ["2730000"]
    run = spec_run(run_tool, steps, num_solutions=2)
    row = run.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2
    assert run.summary["total_api_calls"] == 2


# Spec: ICL alone switches a single-solution agentic row to the list format.
# Context: Agentic Output rules ("when ICL is configured or num_solutions>1").
def test_icl_alone_uses_the_list_format(run_tool):
    icl = icl_block(marker_setups(["chain_of_thought"]))
    run = spec_run(run_tool, ["2730000"], icl=icl)
    row = run.rows[0]
    assert row["output"] == [{"answer": "2730000",
                              "icl_setup": "chain_of_thought"}]
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert len(row["meta"]) == 1


# Spec: "when evaluation is omitted in the checkpoint 3 list format, keep the
#        checkpoint 3 rules: `result.passed` is the number of emitted
#        outputs, `result.failed` is the number of loops that produced no
#        output, and each metadata entry sets `evaluation_passed` to `null`"
# Context: Agentic Output rules.
def test_list_format_without_evaluation(run_tool):
    run = spec_run(run_tool, ["anything at all"], num_solutions=2,
                   evaluation=None)
    row = run.rows[0]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [m["evaluation_passed"] for m in row["meta"]] == [None, None]


def test_list_format_counts_loops_with_no_output_as_failed(run_tool):
    # Every loop runs out of iterations, so no loop emits an output.
    steps = [[("lookup", {"key": "employees"})]]
    run = spec_run(run_tool, steps, EMPLOYEES, num_solutions=2,
                   max_iterations=2, evaluation=None)
    row = run.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [m["finish_reason"] for m in row["meta"]] == ["max_iterations",
                                                         "max_iterations"]


def test_list_format_failed_loops_are_not_emitted_as_outputs(run_tool):
    steps = [[("lookup", {"key": "employees"})]]
    run = spec_run(run_tool, steps, EMPLOYEES, num_solutions=2,
                   max_iterations=2)
    row = run.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [m["evaluation_passed"] for m in row["meta"]] == [False, False]

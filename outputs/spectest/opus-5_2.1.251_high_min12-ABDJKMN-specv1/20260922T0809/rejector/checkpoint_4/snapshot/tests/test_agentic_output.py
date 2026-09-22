"""Spec section: Part 4 / Agentic Output."""
from __future__ import annotations

from conftest import (AGENTIC_ROW, COT_SETUP, DIRECT_SETUP, LOOKUP_TOOL,
                      agentic_config, agentic_replies)
from mock_server import MockAPI


FINAL = "The total revenue for Q1 and Q2 is $2,730,000."
LOOKUP_BOTH = [("lookup", {"key": "revenue_q1"}),
               ("lookup", {"key": "revenue_q2"})]
CALC = [("lookup", {"key": "employees"})]

# The spec's worked example: two tool rounds, then a final answer.
SPEC_SCRIPT = [
    (LOOKUP_BOTH, {"prompt_tokens": 200, "completion_tokens": 30}),
    (CALC, {"prompt_tokens": 350, "completion_tokens": 40}),
    (FINAL, {"prompt_tokens": 300, "completion_tokens": 50}),
]


def run_spec_example(run_tool, write_config, write_input, script=None,
                     **cfg_kw):
    with MockAPI(agentic_replies(script or SPEC_SCRIPT)) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL], **cfg_kw))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    return res


# ---------------------------------------------------------------------------
# Phrase: '"output": {"answer": "The total revenue for Q1 and Q2 is
#          $2,730,000."}'
# Context: Part 4 / Agentic Output - the final text lands under
#          `output_field`.
# ---------------------------------------------------------------------------
def test_output_holds_the_final_text(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] == {"answer": FINAL}


# ---------------------------------------------------------------------------
# Phrase: "`result.iterations` is the number of API requests in the loop"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_iterations_counts_api_requests(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["iterations"] == 3


# Context: same phrase - the simple lookup example: one tool round plus the
# final answer is `result.iterations == 2`.
def test_simple_lookup_example_has_two_iterations(run_tool, write_config,
                                                  write_input):
    script = [CALC, "The company has 142 employees."]
    res = run_spec_example(run_tool, write_config, write_input, script)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["iterations"] == 2
    assert row["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "employees"},
         "result": "142"}]


# ---------------------------------------------------------------------------
# Phrase: "`result.tool_calls` records every tool call in execution order" /
#         "each recorded tool call stores `iteration`, `tool`, parsed `args`,
#          and the handler `result`"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_tool_calls_are_recorded_in_execution_order(run_tool, write_config,
                                                    write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["tool_calls"] == [
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"},
         "result": "1250000"},
        {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"},
         "result": "1480000"},
        {"iteration": 2, "tool": "lookup", "args": {"key": "employees"},
         "result": "142"},
    ]


# ---------------------------------------------------------------------------
# Phrase: "`result.attempts`" (agentic single-solution row shows `1`)
# Context: Part 4 / Agentic Output example (AMBIGUITIES T67).
# ---------------------------------------------------------------------------
def test_attempts_is_one_for_a_single_loop(run_tool, write_config,
                                           write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["attempts"] == 1


# ---------------------------------------------------------------------------
# Phrase: "`meta.total_*` values are aggregated across all iterations"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_meta_totals_are_aggregated(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    meta = res.rows[0]["meta"]
    assert meta["total_prompt_tokens"] == 850
    assert meta["total_completion_tokens"] == 120
    assert meta["total_tokens"] == 970


# ---------------------------------------------------------------------------
# Phrase: "`meta.iterations_detail` records per-iteration token usage,
#          latency, and finish reason"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_iterations_detail_per_iteration(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    detail = res.rows[0]["meta"]["iterations_detail"]
    assert len(detail) == 3
    assert [d["prompt_tokens"] for d in detail] == [200, 350, 300]
    assert [d["completion_tokens"] for d in detail] == [30, 40, 50]
    assert [d["total_tokens"] for d in detail] == [230, 390, 350]
    assert [d["finish_reason"] for d in detail] == ["tool_calls", "tool_calls",
                                                    "stop"]
    assert all(isinstance(d["latency_ms"], int) for d in detail)


# ---------------------------------------------------------------------------
# Phrase: "`meta.latency_ms` is total wall-clock time for the loop"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_latency_is_the_whole_loop(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([CALC, FINAL]), delay=0.2) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL]))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    meta = res.rows[0]["meta"]
    per_iteration = sum(d["latency_ms"] for d in meta["iterations_detail"])
    assert meta["latency_ms"] >= 400
    assert meta["latency_ms"] >= per_iteration


# ---------------------------------------------------------------------------
# Phrase: "`meta.finish_reason` is `\"stop\"` for a final text response and
#          `\"max_iterations\"` when the iteration limit is hit"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_finish_reason_stop(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input)
    assert res.returncode == 0, res
    assert res.rows[0]["meta"]["finish_reason"] == "stop"


def test_finish_reason_max_iterations(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input, [CALC],
                           max_iterations=2)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["meta"]["finish_reason"] == "max_iterations"
    assert row["output"] is None
    assert len(row["meta"]["iterations_detail"]) == 2


# ---------------------------------------------------------------------------
# Phrase: "evaluation runs against the final text output only"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_evaluation_uses_the_final_text(run_tool, write_config, write_input):
    # the tool results contain other numbers; only the final text is judged
    script = [LOOKUP_BOTH, "The total is 2730000."]
    res = run_spec_example(run_tool, write_config, write_input, script)
    assert res.returncode == 0, res
    result = res.rows[0]["result"]
    assert result["extracted_answer"] == "2730000"
    assert result["passed"] is True


def test_evaluation_fails_on_a_wrong_final_text(run_tool, write_config,
                                                write_input):
    script = [LOOKUP_BOTH, "The total is 99."]
    res = run_spec_example(run_tool, write_config, write_input, script)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False
    assert res.rows[0]["result"]["extracted_answer"] == "99"


# ---------------------------------------------------------------------------
# Phrase: "if `max_iterations` is hit, evaluation fails because output is
#          `null`"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_max_iterations_fails_evaluation(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input, [CALC],
                           max_iterations=2)
    assert res.returncode == 0, res
    result = res.rows[0]["result"]
    assert result["passed"] is False
    assert result["extracted_answer"] is None
    assert res.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Phrase: "when evaluation is omitted for a single-solution agentic row, keep
#          the part 1 rule: `result.passed` is `null`, except when
#          `max_iterations` was reached, where it is `false`"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_no_evaluation_passed_is_null(run_tool, write_config, write_input):
    res = run_spec_example(run_tool, write_config, write_input,
                           evaluation=None)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is None
    assert res.rows[0]["output"] == {"answer": FINAL}


def test_no_evaluation_max_iterations_passed_is_false(run_tool, write_config,
                                                      write_input):
    res = run_spec_example(run_tool, write_config, write_input, [CALC],
                           max_iterations=2, evaluation=None)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False
    assert res.rows[0]["output"] is None


# ---------------------------------------------------------------------------
# Phrase: "`agentic` also works with ICL and `num_solutions`; each solution is
#          an independent loop" / "when ICL is configured or
#          `num_solutions > 1`, keep the checkpoint 3 list output format"
# Context: Part 4 / Agentic Output rules and the list-format example.
# ---------------------------------------------------------------------------
def test_num_solutions_produces_the_list_format(run_tool, write_config,
                                                write_input):
    answer = "The total is 2730000."
    with MockAPI(agentic_replies([answer])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          num_solutions=2))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2                       # two independent loops
    row = res.rows[0]
    assert row["output"] == [{"answer": answer, "icl_setup": None},
                             {"answer": answer, "icl_setup": None}]
    assert row["result"]["attempts"] == 2
    assert row["result"]["failed"] == 0
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2


# Context: same example - "`result.passed` is `2`" when both loops answer
# correctly on their first API request.
def test_list_format_result_counts(run_tool, write_config, write_input):
    with MockAPI(agentic_replies(["The total is 2730000."])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          num_solutions=2))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}


# ---------------------------------------------------------------------------
# Phrase: "in that list format, `result.attempts` is the number of loops
#          started for the row, not the number of API requests across those
#          loops"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_list_format_attempts_counts_loops_not_requests(run_tool, write_config,
                                                        write_input):
    with MockAPI(agentic_replies([CALC, FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          num_solutions=2))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 4                       # two loops x two requests
    assert res.rows[0]["result"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Phrase: "per-loop agentic metadata lives in each `meta` entry: keep
#          checkpoint 3's `icl_setup` / `evaluation_passed` fields and also
#          record that loop's aggregated `total_prompt_tokens`,
#          `total_completion_tokens`, `total_tokens`, `latency_ms`,
#          `finish_reason`, and `iterations_detail`"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_list_format_meta_entries_carry_agentic_metadata(run_tool,
                                                         write_config,
                                                         write_input):
    script = [
        (CALC, {"prompt_tokens": 200, "completion_tokens": 30}),
        ("The total is 2730000.", {"prompt_tokens": 350,
                                   "completion_tokens": 40}),
    ]
    with MockAPI(agentic_replies(script)) as api:
        cfg = write_config(agentic_config(
            api.url, [LOOKUP_TOOL], num_solutions=2,
            icl={"setups": [COT_SETUP, DIRECT_SETUP],
                 "strategy": "round_robin"}))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    metas = res.rows[0]["meta"]
    assert len(metas) == 2
    for entry in metas:
        assert entry["total_prompt_tokens"] == 550
        assert entry["total_completion_tokens"] == 70
        assert entry["total_tokens"] == 620
        assert entry["finish_reason"] == "stop"
        assert isinstance(entry["latency_ms"], int)
        assert len(entry["iterations_detail"]) == 2
        assert entry["evaluation_passed"] is True
    assert [e["icl_setup"] for e in metas] == ["chain_of_thought", "direct"]
    assert [o["icl_setup"] for o in res.rows[0]["output"]] == [
        "chain_of_thought", "direct"]


# ---------------------------------------------------------------------------
# Phrase: "when evaluation is omitted in the checkpoint 3 list format, keep
#          the checkpoint 3 rules: `result.passed` is the number of emitted
#          outputs, `result.failed` is the number of loops that produced no
#          output, and each metadata entry sets `evaluation_passed` to `null`"
# Context: Part 4 / Agentic Output rules.
# ---------------------------------------------------------------------------
def test_list_format_without_evaluation(run_tool, write_config, write_input):
    with MockAPI(agentic_replies([FINAL])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          num_solutions=3, evaluation=None))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert all(m["evaluation_passed"] is None for m in row["meta"])


# Context: same phrase - a loop that hits `max_iterations` emits no output and
# counts as failed (AMBIGUITIES T89).
def test_list_format_max_iterations_loop_counts_as_failed(run_tool,
                                                          write_config,
                                                          write_input):
    with MockAPI(agentic_replies([CALC])) as api:
        cfg = write_config(agentic_config(api.url, [LOOKUP_TOOL],
                                          num_solutions=2, max_iterations=2,
                                          evaluation=None))
        data = write_input([AGENTIC_ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 4
    row = res.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [m["finish_reason"] for m in row["meta"]] == ["max_iterations",
                                                          "max_iterations"]

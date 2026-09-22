"""Agentic rows in the checkpoint 3 list format: ICL and `num_solutions`."""

from __future__ import annotations

from conftest import agentic_config, icl_setup, setups_used, turn_responder
from mock_server import Reply

ROW = [{"question": "How many employees?", "answer": "142"}]
LOOKUP = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
ANSWER = Reply(content="The company has 142 employees.")
SETUPS = [icl_setup("chain_of_thought", "142"), icl_setup("direct", "142")]

META_KEYS = {
    "icl_setup",
    "evaluation_passed",
    "total_prompt_tokens",
    "total_completion_tokens",
    "total_tokens",
    "latency_ms",
    "finish_reason",
    "iterations_detail",
}


def run(servers, run_cli, *replies, **overrides):
    server = servers(responder=turn_responder(*replies))
    result = run_cli(agentic_config(server.url, **overrides), ROW)
    assert result.exit_code == 0, result.stderr
    return server, result.rows[0]


# Spec: "if `num_solutions: 2` and both loops produce a final answer on their
# first API request ... `output` follows the checkpoint 3 list format with two
# items ... `result.passed` is `2`, `result.failed` is `0`, and
# `result.attempts` is `2`".
def test_two_solutions_produce_two_output_items(servers, run_cli):
    server, row = run(servers, run_cli, ANSWER, num_solutions=2)
    assert row["output"] == [
        {"answer": "The company has 142 employees.", "icl_setup": None},
        {"answer": "The company has 142 employees.", "icl_setup": None},
    ]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(row["meta"]) == 2
    assert server.call_count == 2


# Spec: "`agentic` also works with ICL and `num_solutions`; each solution is an
# independent loop" -- two loops of two requests each.
def test_each_solution_runs_its_own_loop(servers, run_cli):
    server, row = run(servers, run_cli, LOOKUP, ANSWER, num_solutions=2)
    assert server.call_count == 4
    assert len(row["output"]) == 2


# Spec: "in that list format, `result.attempts` is the number of loops started
# for the row, not the number of API requests across those loops".
def test_attempts_counts_loops_not_requests(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, ANSWER, num_solutions=2)
    assert row["result"]["attempts"] == 2


# Spec: "per-loop agentic metadata lives in each `meta` entry: keep checkpoint
# 3's `icl_setup` / `evaluation_passed` fields and also record that loop's
# aggregated `total_prompt_tokens`, `total_completion_tokens`, `total_tokens`,
# `latency_ms`, `finish_reason`, and `iterations_detail`". (T66)
def test_meta_entry_carries_aggregated_agentic_metadata(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, ANSWER, num_solutions=2)
    entry = row["meta"][0]
    assert set(entry) == META_KEYS
    assert entry["evaluation_passed"] is True
    assert entry["icl_setup"] is None
    assert entry["total_tokens"] == 330
    assert len(entry["iterations_detail"]) == 2


# Spec: "when ICL is configured or `num_solutions > 1`, keep the checkpoint 3
# list output format" -- ICL alone is enough.
def test_icl_alone_uses_the_list_format(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, ANSWER, icl={"setups": SETUPS})
    assert row["output"] == [
        {"answer": "The company has 142 employees.", "icl_setup": "chain_of_thought"}
    ]
    assert row["meta"][0]["icl_setup"] == "chain_of_thought"


# Spec: "each emitted output item represents one completed agentic loop" -- the
# ICL strategy still chooses a setup per loop.
def test_icl_strategy_selects_a_setup_per_loop(servers, run_cli):
    server, row = run(
        servers,
        run_cli,
        ANSWER,
        num_solutions=2,
        icl={"setups": SETUPS, "strategy": "round_robin"},
    )
    assert setups_used(server) == ["chain_of_thought", "direct"]
    assert [item["icl_setup"] for item in row["output"]] == [
        "chain_of_thought",
        "direct",
    ]


# Spec: "if `max_iterations` is hit ... output `null`" -- such a loop emits no
# output item, so the row's counts record it as failed.
def test_max_iteration_loops_emit_no_output(servers, run_cli):
    _, row = run(
        servers,
        run_cli,
        LOOKUP,
        num_solutions=2,
        generation={"max_iterations": 2},
    )
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [entry["finish_reason"] for entry in row["meta"]] == [
        "max_iterations",
        "max_iterations",
    ]


# Spec: "when evaluation is omitted in the checkpoint 3 list format ...
# `result.passed` is the number of emitted outputs, `result.failed` is the
# number of loops that produced no output, and each metadata entry sets
# `evaluation_passed` to `null`".
def test_list_format_without_evaluation(servers, run_cli):
    _, row = run(servers, run_cli, LOOKUP, ANSWER, num_solutions=2, evaluation=None)
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [entry["evaluation_passed"] for entry in row["meta"]] == [None, None]


# Spec: "`result.failed` is the number of loops that produced no output" with
# no evaluation configured.
def test_list_format_without_evaluation_counts_empty_loops(servers, run_cli):
    _, row = run(
        servers,
        run_cli,
        LOOKUP,
        num_solutions=2,
        evaluation=None,
        generation={"max_iterations": 2},
    )
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}

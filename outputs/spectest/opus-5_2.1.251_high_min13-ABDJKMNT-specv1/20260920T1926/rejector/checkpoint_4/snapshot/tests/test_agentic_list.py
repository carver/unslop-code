"""Agentic rows that keep the checkpoint 3 list format: ICL and num_solutions."""

from __future__ import annotations

from conftest import agentic_task, icl_block, inline_setup
from fake_api import FakeAPI, Reply, always, call, turns

ROW = {"question": "How many employees?", "answer": "142"}

LOOKUP = Reply(content=None, tools=(call("lookup", key="employees"),))
FINAL = Reply(content="The company has 142 employees.", prompt_tokens=40, completion_tokens=6)

COT = inline_setup("chain_of_thought", "142")
DIRECT = inline_setup("direct", "142")


def two_solutions(api_url: str, **overrides) -> dict:
    """The spec's agentic task running two independent loops per row."""
    return agentic_task(api_url, num_solutions=2, **overrides)


# Spec: "if `num_solutions: 2` and both loops produce a final answer on their
# first API request ... `result.passed` is `2`, `result.failed` is `0`, and
# `result.attempts` is `2`"
# Context: Examples / Agentic list-format run.
def test_two_loops_report_the_list_format(write_config, write_input, run_cli):
    with FakeAPI(responder=always("The company has 142 employees.")) as api:
        result = run_cli(write_config(two_solutions(api.url)), write_input([ROW]))
        assert api.call_count == 2
    row = result.rows[0]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert len(row["output"]) == 2
    assert row["output"][0]["answer"] == "The company has 142 employees."


# Spec: "`meta` is a list with two entries, one aggregated agentic metadata
# object per loop"
# Context: Examples / Agentic list-format run.
def test_meta_is_one_aggregated_object_per_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=always("The company has 142 employees.")) as api:
        result = run_cli(write_config(two_solutions(api.url)), write_input([ROW]))
    meta = result.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 2
    assert set(meta[0]) == {
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "iterations_detail",
        "icl_setup",
        "evaluation_passed",
    }


# Spec: "keep checkpoint 3's `icl_setup` / `evaluation_passed` fields and also
# record that loop's aggregated ... `finish_reason`, and `iterations_detail`"
# Context: Agentic Output / Rules.
def test_each_meta_entry_carries_its_loop_totals(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        result = run_cli(write_config(two_solutions(api.url)), write_input([ROW]))
    entry = result.rows[0]["meta"][0]
    assert entry["finish_reason"] == "stop"
    assert len(entry["iterations_detail"]) == 2
    assert entry["total_prompt_tokens"] == 10 + 40
    assert entry["total_completion_tokens"] == 20 + 6
    assert entry["evaluation_passed"] is True
    assert entry["icl_setup"] is None


# Spec: "`agentic` also works with ICL and `num_solutions`; each solution is
# an independent loop"
# Context: Agentic Output / Rules.
def test_icl_examples_open_each_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=always("The company has 142 employees.")) as api:
        task = agentic_task(api.url, icl=icl_block([COT, DIRECT], strategy="round_robin"))
        task["num_solutions"] = 2
        result = run_cli(write_config(task), write_input([ROW]))
        roles = [message["role"] for message in api.requests[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert [item["icl_setup"] for item in result.rows[0]["output"]] == [
        "chain_of_thought",
        "direct",
    ]


# Spec: "in that list format, `result.attempts` is the number of loops started
# for the row, not the number of API requests across those loops"
# Context: Agentic Output / Rules.
def test_attempts_counts_loops_not_requests(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, LOOKUP, FINAL])) as api:
        result = run_cli(write_config(two_solutions(api.url)), write_input([ROW]))
        assert api.call_count == 6
    assert result.rows[0]["result"]["attempts"] == 2
    assert result.summary["total_api_calls"] == 6


# Spec: "each emitted output item represents one completed agentic loop"
# Context: Agentic Output / Rules; a loop that hit its limit emits nothing.
def test_a_limited_loop_emits_no_output_item(write_config, write_input, run_cli):
    with FakeAPI(responder=always(None, tools=(call("lookup", key="employees"),))) as api:
        task = two_solutions(api.url)
        task["generation"]["max_iterations"] = 2
        result = run_cli(write_config(task), write_input([ROW]))
    row = result.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert [entry["finish_reason"] for entry in row["meta"]] == [
        "max_iterations",
        "max_iterations",
    ]


# Spec: "when evaluation is omitted in the checkpoint 3 list format ...
# `result.passed` is the number of emitted outputs, `result.failed` is the
# number of loops that produced no output, and each metadata entry sets
# `evaluation_passed` to `null`"
# Context: Agentic Output / Rules.
def test_list_format_without_evaluation(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        task = two_solutions(api.url)
        del task["evaluation"]
        result = run_cli(write_config(task), write_input([ROW]))
    row = result.rows[0]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [entry["evaluation_passed"] for entry in row["meta"]] == [None, None]


# Spec: "in that list format ... per-loop agentic metadata lives in each
# `meta` entry"
# Context: Agentic Output / Rules; `result` keeps the checkpoint 3 keys only.
def test_list_result_keeps_the_checkpoint_three_keys(write_config, write_input, run_cli):
    with FakeAPI(responder=turns([LOOKUP, FINAL])) as api:
        result = run_cli(write_config(two_solutions(api.url)), write_input([ROW]))
    assert set(result.rows[0]["result"]) == {"passed", "failed", "attempts"}

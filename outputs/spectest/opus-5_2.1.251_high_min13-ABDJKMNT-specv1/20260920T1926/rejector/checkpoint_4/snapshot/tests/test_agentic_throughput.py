"""Agentic loops must not serialise the rows they run for."""

from __future__ import annotations

from conftest import agentic_task
from fake_api import FakeAPI, Reply, call, turns

# Three rows, each needing a tool call and then a final answer.
ROWS = [{"question": f"q{index}", "answer": "142"} for index in range(3)]
SCRIPT = [
    Reply(content=None, tools=(call("lookup", key="employees"),)),
    Reply(content="The company has 142 employees."),
]


# Spec: "a single agentic run may span many API requests, but other inputs
# must still be able to make progress concurrently"
# Context: Agentic loop / Rules.
def test_rows_progress_concurrently(write_config, write_input, run_cli):
    with FakeAPI(responder=turns(SCRIPT), slots=8, delay=0.3) as api:
        run_cli(write_config(agentic_task(api.url)), write_input(ROWS))
        assert api.max_concurrent > 1


# Spec: "do not fully serialize short batches; for example, if three input
# rows are all pending and each needs a tool call followed by a final answer,
# requests from different rows should still be able to overlap in flight"
# Context: Agentic loop / Rules.
def test_a_three_row_batch_is_not_serialised(write_config, write_input, run_cli):
    with FakeAPI(responder=turns(SCRIPT), slots=8, delay=0.3) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input(ROWS))
        assert api.call_count == 6
        assert api.max_concurrent == 3
    assert result.summary["elapsed_seconds"] < 6 * 0.3


# Spec: "each API request inside the loop counts separately toward request
# totals"
# Context: Agentic loop / Rules; every row still keeps its own answers.
def test_each_row_keeps_its_own_loop(write_config, write_input, run_cli):
    with FakeAPI(responder=turns(SCRIPT), slots=8, delay=0.2) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input(ROWS))
    assert [row["input"]["question"] for row in result.rows] == ["q0", "q1", "q2"]
    assert all(row["result"]["iterations"] == 2 for row in result.rows)
    assert result.summary["total_api_calls"] == 6

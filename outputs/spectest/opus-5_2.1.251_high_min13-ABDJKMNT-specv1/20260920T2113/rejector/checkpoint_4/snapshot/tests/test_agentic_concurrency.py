"""Agentic loops of different rows must overlap in flight."""

from __future__ import annotations

from tests.conftest import agentic_config, lookup_then_answer

ANSWER = "The company has 142 employees."
ROWS = [{"question": f"How many? {index}", "answer": "142"} for index in range(3)]


# "a single agentic run may span many API requests, but other inputs must still
#  be able to make progress concurrently"
# "do not fully serialize short batches; for example, if three input rows are
#  all pending and each needs a tool call followed by a final answer, requests
#  from different rows should still be able to overlap in flight"
def test_three_rows_overlap_their_loop_requests(cli, api):
    server = api(lookup_then_answer("employees", "142", ANSWER), delay=0.2)
    run = cli.run(agentic_config(api_url=server.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 6
    assert server.log.max_in_flight >= 2
    assert all(row["output"] == {"answer": ANSWER} for row in run.rows)


# Overlap is not achieved by reordering: rows stay in input order on the way out.
def test_rows_keep_input_order(cli, api):
    server = api(lookup_then_answer("employees", "142", ANSWER), delay=0.05)
    run = cli.run(agentic_config(api_url=server.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert [row["input"]["question"] for row in run.rows] == \
        [row["question"] for row in ROWS]


# A tool handler that shells out must not block the other rows' loops.
def test_script_handlers_do_not_block_other_rows(cli, api):
    server = api(lookup_then_answer("print(6 * 7)", "42", ANSWER), delay=0.2)
    config = agentic_config(api_url=server.url)
    config["task"]["tools"][0]["handler"] = {
        "type": "script", "command": "python3 -c", "arg_field": "key",
    }
    run = cli.run(config, ROWS)
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 6
    assert server.log.max_in_flight >= 2

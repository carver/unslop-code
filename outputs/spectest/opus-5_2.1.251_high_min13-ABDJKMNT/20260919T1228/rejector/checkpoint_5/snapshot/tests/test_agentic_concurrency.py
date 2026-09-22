"""Agentic loops must not serialize the rows that are waiting behind them."""

from __future__ import annotations

from conftest import agentic_config, turn_responder
from mock_server import Reply

LOOKUP = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
ANSWER = Reply(content="The company has 142 employees.")
ROWS = [{"question": f"q{index}", "answer": "142"} for index in range(3)]


# Spec: "do not fully serialize short batches; for example, if three input rows
# are all pending and each needs a tool call followed by a final answer,
# requests from different rows should still be able to overlap in flight".
def test_rows_overlap_in_flight(servers, run_cli):
    server = servers(responder=turn_responder(LOOKUP, ANSWER), service_time=0.3)
    result = run_cli(agentic_config(server.url, rpm=600), ROWS)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 6
    assert server.peak_concurrency >= 3


# Spec: "a single agentic run may span many API requests, but other inputs must
# still be able to make progress concurrently" -- six requests at 0.3s each
# take about two rounds, not six.
def test_batch_finishes_in_about_two_rounds(servers, run_cli):
    server = servers(responder=turn_responder(LOOKUP, ANSWER), service_time=0.3)
    result = run_cli(agentic_config(server.url, rpm=600), ROWS)
    assert result.summary["elapsed_seconds"] < 1.2

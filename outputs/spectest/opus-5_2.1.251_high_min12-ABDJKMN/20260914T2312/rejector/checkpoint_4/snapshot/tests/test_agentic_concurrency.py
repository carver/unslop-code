"""Checkpoint 4 throughput: agentic loops must not serialize the batch."""

import time

from fake_api import FakeAPI, agentic, calls, final


SCRIPT = [calls(("lookup", {"key": "employees"})), final("142")]


# "a single agentic run may span many API requests, but other inputs must
#  still be able to make progress concurrently"
# "do not fully serialize short batches; for example, if three input rows are
#  all pending and each needs a tool call followed by a final answer, requests
#  from different rows should still be able to overlap in flight"
def test_three_rows_overlap_in_flight(run_agentic):
    rows = [{"question": "q%d" % i, "answer": "142"} for i in range(3)]
    with FakeAPI(agentic(SCRIPT), latency=0.25) as server:
        started = time.time()
        res = run_agentic(server, rows=rows, check=0)
        elapsed = time.time() - started
    assert server.call_count == 6
    assert server.max_inflight >= 2, "agentic rows were fully serialized"
    # Six serialized 0.25s requests would take >= 1.5s; overlapping rows make
    # the whole batch take about two request times.
    assert elapsed < 1.4
    assert all(r["result"]["iterations"] == 2 for r in res.rows)


def test_a_long_loop_does_not_block_other_rows(run_agentic):
    # One row spins through many tool calls; the other must not wait for it.
    per_row = {"slow": [calls(("lookup", {"key": "employees"}))],
               "fast": [final("142")]}
    rows = [{"question": "slow", "answer": "142"},
            {"question": "fast", "answer": "142"}]
    with FakeAPI(agentic([final("142")], per_row=per_row),
                 latency=0.1) as server:
        res = run_agentic(server,
                          task={"num_solutions": None,
                                "generation": {"scheme": "agentic",
                                               "max_iterations": 8,
                                               "temperature": 0.0,
                                               "max_tokens": 512}},
                          rows=rows, check=0)
    slow, fast = res.rows
    assert slow["result"]["iterations"] == 8
    assert fast["result"]["iterations"] == 1
    # The fast row finished long before the slow row's eight requests did.
    fast_calls = [r for r in server.requests if "fast" in str(r.row_key)]
    slow_calls = [r for r in server.requests if "slow" in str(r.row_key)]
    assert fast_calls[-1].finished < slow_calls[-1].finished
    assert server.max_inflight >= 2

"""Spec section: Throughput (concurrency, rpm target, request ordering)."""
from __future__ import annotations

import time

from conftest import base_config
from mock_server import MockAPI, always, completion


# ---------------------------------------------------------------------------
# Phrase: "The tool must issue requests concurrently."
# Context: Throughput.  With a per-request server delay, a sequential client
# would take rows*delay; a concurrent one takes far less.
# ---------------------------------------------------------------------------
def test_requests_are_concurrent(run_tool, write_config, write_input):
    rows = 20
    delay = 0.3
    with MockAPI(always("#### 5"), delay=delay) as api:
        cfg = write_config(base_config(api.url, rpm=600))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(rows)])
        start = time.time()
        res = run_tool(cfg, data)
        wall = time.time() - start
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert peak > 1, "requests were issued one at a time"
    assert wall < rows * delay * 0.5


# ---------------------------------------------------------------------------
# Phrase: "A sequential client will leave capacity idle; your tool should keep
#          enough requests in flight to use the configured request budget
#          effectively."
# Context: Overview.  The server processes `capacity` requests at a time; the
# client should keep that pipeline full.
# ---------------------------------------------------------------------------
def test_server_pipeline_is_kept_busy(run_tool, write_config, write_input):
    capacity = 8
    with MockAPI(always("#### 5"), delay=0.15, capacity=capacity) as api:
        cfg = write_config(base_config(api.url, rpm=480))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(40)])
        res = run_tool(cfg, data)
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert peak >= capacity


# ---------------------------------------------------------------------------
# Phrase: "Target at least 80% of the configured rpm."
# Context: Throughput.  Server capacity is set to match the configured rpm.
# ---------------------------------------------------------------------------
def test_throughput_reaches_80_percent_of_rpm(run_tool, write_config,
                                              write_input):
    rpm = 600                      # 10 requests/second of server capacity
    delay = 0.2                    # each request takes 200ms to process
    capacity = 2                   # 2 slots x 200ms == 10 req/s == 600 rpm
    with MockAPI(always("#### 5"), delay=delay, capacity=capacity) as api:
        cfg = write_config(base_config(api.url, rpm=rpm))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(60)])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.summary["throughput_rpm"] >= 0.8 * rpm, res.summary


# ---------------------------------------------------------------------------
# Phrase: "Send requests in input order"
# Context: Throughput.  Requests must be *issued* in row order.
# ---------------------------------------------------------------------------
def test_requests_issued_in_input_order(run_tool, write_config, write_input):
    # A small in-flight window means a row may only be issued once the rows
    # well ahead of it have already gone out.  (Part 5 turned `rpm` into a
    # real sliding-window budget, so the window is set with `max_concurrent`.)
    window = 4
    rows = 20
    with MockAPI(always("#### 5"), delay=0.05, capacity=1) as api:
        cfg = write_config(base_config(
            api.url, rpm=600, rate_limits={"max_concurrent": window}))
        data = write_input([{"question": str(i), "answer": "5"}
                            for i in range(rows)])
        res = run_tool(cfg, data)
        order = [int(r["messages"][-1]["content"]) for r in api.requests]
    assert res.returncode == 0, res
    assert sorted(order) == list(range(rows))
    # No row runs ahead of the earlier rows by more than the in-flight window,
    # i.e. requests go out in input order up to concurrency reordering.
    for position, index in enumerate(order):
        assert index <= position + window, order


# ---------------------------------------------------------------------------
# Phrase: "concurrent execution must not cause a later input row to consume the
#          response intended for an earlier row"
# Context: Throughput.  Each reply is keyed to its own prompt; every row must
# receive the reply generated for it, whatever the completion order.
# ---------------------------------------------------------------------------
def test_responses_are_not_crossed(run_tool, write_config, write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        index = int(user[1:])
        # Earlier rows are answered slowest, forcing out-of-order completion.
        time.sleep(max(0.0, (10 - index) * 0.04))
        return 200, completion(f"the answer is #### {index}")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url, rpm=600))
        data = write_input([{"question": f"q{i}", "answer": str(i)}
                            for i in range(10)])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    rows = res.rows
    assert len(rows) == 10
    for i, row in enumerate(rows):
        assert row["input"]["question"] == f"q{i}"
        assert row["output"]["solution"].endswith(f"#### {i}")
        assert row["result"]["passed"] is True


# Context: Throughput - rejection attempts for the same row are sequential
# (each attempt depends on the previous one's verdict) but rows still overlap.
def test_rejection_rows_overlap(run_tool, write_config, write_input):
    with MockAPI(always("#### 0"), delay=0.1) as api:
        cfg = write_config(base_config(
            api.url, rpm=600,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(8)])
        start = time.time()
        res = run_tool(cfg, data)
        wall = time.time() - start
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert api.call_count == 24
    assert peak > 1
    assert wall < 24 * 0.1 * 0.6

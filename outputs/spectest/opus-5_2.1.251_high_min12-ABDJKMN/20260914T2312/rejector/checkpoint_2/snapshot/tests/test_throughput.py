"""Concurrency requirements from the Throughput section."""

import time

import pytest

import fake_api


# ---------------------------------------------------------------------------
# Spec: "The tool must issue requests concurrently."
# Context: Throughput.  The server observes more than one request in flight.
# ---------------------------------------------------------------------------
def test_requests_are_issued_concurrently(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(20)]
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.2) as api:
        run_task(api, task={"rpm": 300}, rows=rows, check=0)
        assert api.max_inflight > 1


# ---------------------------------------------------------------------------
# Spec: "A sequential client will leave capacity idle" / "keep enough work in
#        flight to avoid an obviously sequential pipeline."
# Context: Throughput.  Wall-clock must be far below the sequential bound.
# ---------------------------------------------------------------------------
def test_wall_clock_beats_a_sequential_pipeline(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(30)]
    started = time.time()
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.3) as api:
        run_task(api, task={"rpm": 300}, rows=rows, check=0)
    elapsed = time.time() - started
    sequential = 30 * 0.3
    assert elapsed < sequential / 2


# ---------------------------------------------------------------------------
# Spec: "Target at least 80% of the configured rpm."
# Context: Throughput.  rpm=300 with a 0.3s server means a sequential client
# tops out at 200 rpm; the reported throughput must clear 240.
# ---------------------------------------------------------------------------
def test_throughput_reaches_80_percent_of_configured_rpm(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(30)]
    with fake_api.FakeAPI(fake_api.always("#### 5"), latency=0.3) as api:
        res = run_task(api, task={"rpm": 300}, rows=rows, check=0)
    assert res.summary["throughput_rpm"] >= 0.8 * 300


# ---------------------------------------------------------------------------
# Spec: "your tool should keep enough requests in flight to use the configured
#        request budget effectively"
# Context: Throughput.  Rejection attempts are sequential within a row
# (AMBIGUITIES T14), but rows still overlap.
# ---------------------------------------------------------------------------
def test_rejection_rows_run_concurrently(run_task):
    rows = [{"question": "q%d" % i, "answer": "42"} for i in range(10)]
    with fake_api.FakeAPI(fake_api.always("#### 1"), latency=0.15) as api:
        res = run_task(api,
                       task={"rpm": 300,
                             "generation": {"scheme": "rejection",
                                            "temperature": 0.8, "n": 2},
                             "evaluation": {"type": "exact_match",
                                            "answer_field": "answer",
                                            "extract": "last_number"}},
                       rows=rows, check=0)
        assert api.max_inflight > 1
    assert res.summary["total_api_calls"] == 20


# ---------------------------------------------------------------------------
# Spec: "The API server queues requests internally and spends time processing
#        each request."
# Context: Throughput.  A server that only processes a few at a time still
# yields correct, in-order results.
# ---------------------------------------------------------------------------
def test_queued_server_still_returns_correct_rows(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(15)]
    with fake_api.FakeAPI(fake_api.echo_user(), latency=0.05, capacity=3) as api:
        res = run_task(api, task={"rpm": 120, "evaluation": None},
                       rows=rows, check=0)
    assert [r["output"]["solution"] for r in res.rows] == \
           ["q%d" % i for i in range(15)]

"""Concurrency: the pipeline must not be sequential and must approach rpm."""
import pytest

from conftest import make_config
from mock_api import MockAPI, always


# Spec: "The tool must issue requests concurrently. ... keep enough work in
#        flight to avoid an obviously sequential pipeline."
# Context: Throughput.
def test_requests_overlap_in_flight(run_tool):
    # 20 rows against a server that holds each request for 0.2s. A sequential
    # client would only ever have one request in flight.
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(20)]
    with MockAPI(always("#### 5"), service_seconds=0.2, capacity_rpm=1200) as api:
        run = run_tool(make_config(api_url=api.url, rpm=1200), rows)
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent > 1


# Spec: "Use the configured rpm as the server's approximate request capacity
#        and keep enough work in flight ... Target at least 80% of the
#        configured rpm."
# Context: Throughput.
def test_throughput_reaches_80_percent_of_configured_rpm(run_tool):
    rpm = 1200
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(40)]
    with MockAPI(always("#### 5"), service_seconds=0.2, capacity_rpm=rpm) as api:
        run = run_tool(make_config(api_url=api.url, rpm=rpm), rows)
    assert run.returncode == 0, run.stderr
    assert run.summary["throughput_rpm"] >= 0.8 * rpm


# Spec: "A sequential client will leave capacity idle"
# Context: Overview. Total wall clock must be far below rows * service time.
def test_wall_clock_far_below_sequential_time(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(30)]
    with MockAPI(always("#### 5"), service_seconds=0.2, capacity_rpm=1800) as api:
        run = run_tool(make_config(api_url=api.url, rpm=1800), rows)
    assert run.returncode == 0, run.stderr
    sequential = 30 * 0.2
    assert run.summary["elapsed_seconds"] < sequential / 2


# Spec: rejection attempts for one row are sequential, but rows still overlap.
def test_rejection_rows_run_concurrently(run_tool):
    rows = [{"question": "q%d" % i, "answer": "42"} for i in range(10)]
    with MockAPI(always("#### 0"), service_seconds=0.15, capacity_rpm=1200) as api:
        run = run_tool(make_config(api_url=api.url, rpm=1200, scheme="rejection",
                                   temperature=0.7, n=2), rows)
    assert run.returncode == 0, run.stderr
    assert api.max_concurrent > 1
    assert run.summary["total_api_calls"] == 20

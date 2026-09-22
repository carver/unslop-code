"""Concurrency: saturating the configured request budget while keeping order."""

from __future__ import annotations

from conftest import base_task
from fake_api import FakeAPI, Reply, always, by_question

# The fake server serves `slots` requests at a time, each taking `delay`
# seconds, so its capacity is slots/delay requests per second. These tests use
# 5 slots at 0.5s = 10 req/s = 600 rpm, matching the configured rpm below.
SLOTS = 5
DELAY = 0.5
RPM = 600


# Spec: "The tool must issue requests concurrently." / "A sequential client
# will leave capacity idle".
# Context: Throughput.
def test_requests_overlap_in_flight(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=SLOTS, delay=DELAY) as api:
        task = base_task(api.url)
        task["rpm"] = RPM
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(30)])
        run_cli(config, data)
        assert api.max_concurrent > 1


# Spec: "Target at least 80% of the configured rpm."
# Context: Throughput.
def test_throughput_reaches_eighty_percent_of_rpm(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=SLOTS, delay=DELAY) as api:
        task = base_task(api.url)
        task["rpm"] = RPM
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(30)])
        result = run_cli(config, data)
    assert result.summary["throughput_rpm"] >= 0.8 * RPM


# Spec: "Send requests in input order: concurrent execution must not cause a
# later input row to consume the response intended for an earlier row."
# Context: Throughput. Rows are admitted to the worker pool in order, so an
# arrival can only be displaced by the number of requests kept in flight.
def test_requests_are_dispatched_in_input_order(write_config, write_input, run_cli):
    in_flight = 8
    with FakeAPI(responder=always("#### 5"), slots=SLOTS, delay=DELAY) as api:
        task = base_task(api.url)
        task["rpm"] = in_flight
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(24)])
        run_cli(config, data)
        arrivals = [
            int(body["messages"][-1]["content"][1:]) for body in api.requests
        ]
    assert sorted(arrivals) == list(range(24))
    assert all(row <= position + in_flight for position, row in enumerate(arrivals))


# Spec: "concurrent execution must not cause a later input row to consume the
# response intended for an earlier row."
# Context: Throughput; responses come back out of order here.
def test_out_of_order_responses_stay_with_their_row(write_config, write_input, run_cli):
    rows = [{"question": f"q{i}", "answer": str(i)} for i in range(20)]
    # Later rows are served fast, early rows slowly, so completions interleave.
    mapping = {f"q{i}": Reply(content=f"#### {i}") for i in range(20)}
    with FakeAPI(responder=by_question(mapping), slots=SLOTS, delay=DELAY) as api:
        task = base_task(api.url)
        task["rpm"] = RPM
        config = write_config(task)
        data = write_input(rows)
        result = run_cli(config, data)
    for index, row in enumerate(result.rows):
        assert row["output"]["solution"] == f"#### {index}"
        assert row["input"]["question"] == f"q{index}"
        assert row["result"]["passed"] is True


# Spec: "keep enough work in flight to avoid an obviously sequential pipeline"
# Context: Throughput; rejection rows are sequential within a row but the rows
# themselves still overlap.
def test_rejection_rows_overlap_across_rows(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1"), slots=SLOTS, delay=DELAY) as api:
        task = base_task(api.url)
        task["rpm"] = RPM
        task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 2}
        config = write_config(task)
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(15)])
        result = run_cli(config, data)
        assert api.max_concurrent > 1
    assert result.summary["total_api_calls"] == 30

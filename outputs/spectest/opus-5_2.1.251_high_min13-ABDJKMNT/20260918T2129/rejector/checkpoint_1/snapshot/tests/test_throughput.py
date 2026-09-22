"""Concurrency: the client must keep enough requests in flight."""

from __future__ import annotations

import pytest
from fake_server import FakeAPIServer, Reply, completion
from conftest import base_config

# The fake server processes `CAPACITY` requests at a time, each taking
# `SERVICE_SECONDS`, so its ceiling is CAPACITY / SERVICE_SECONDS * 60 rpm.
CAPACITY = 4
SERVICE_SECONDS = 0.4
RPM = int(CAPACITY / SERVICE_SECONDS * 60)  # 600


def _slow(payload, index):
    return Reply(completion("#### 5"), delay=SERVICE_SECONDS)


# Spec: "The tool must issue requests concurrently ... Target at least 80% of
# the configured rpm."
@pytest.mark.slow
def test_throughput_reaches_80_percent_of_configured_rpm(write_config, write_input, run_cli):
    with FakeAPIServer(_slow, capacity=CAPACITY) as api:
        config_map = base_config(api.url)
        config_map["task"]["rpm"] = RPM
        config = write_config(config_map)
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(60)])
        result = run_cli(config, rows)

    assert result.summary["throughput_rpm"] >= 0.8 * RPM


# Spec: "keep enough requests in flight to use the configured request budget
# effectively" - an obviously sequential pipeline is not acceptable
@pytest.mark.slow
def test_multiple_requests_are_in_flight_at_once(write_config, write_input, run_cli):
    with FakeAPIServer(_slow, capacity=CAPACITY) as api:
        config_map = base_config(api.url)
        config_map["task"]["rpm"] = RPM
        config = write_config(config_map)
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(30)])
        run_cli(config, rows)
        peak = api.peak_in_flight

    assert peak >= CAPACITY


# Spec: "rejection ... up to n attempts" still runs rows concurrently
@pytest.mark.slow
def test_rejection_rows_run_concurrently(write_config, write_input, run_cli):
    with FakeAPIServer(_slow, capacity=CAPACITY) as api:
        config_map = base_config(api.url)
        config_map["task"]["rpm"] = RPM
        config_map["task"]["generation"] = {
            "scheme": "rejection", "temperature": 0.7, "n": 2, "max_tokens": 64,
        }
        config = write_config(config_map)
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(20)])
        run_cli(config, rows)
        peak = api.peak_in_flight

    assert peak >= CAPACITY

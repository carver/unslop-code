"""Concurrency: the tool must keep the server's request budget busy."""

from __future__ import annotations

from conftest import make_config


# Spec: "The tool must issue requests concurrently ... Target at least 80% of
# the configured rpm." The mock server serves 4 requests at a time, each
# taking 0.4s -> a capacity of 600 requests/minute.
def test_throughput_reaches_80_percent_of_rpm(servers, run_cli):
    server = servers(contents=["#### 8"], service_time=0.4, workers=4)
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(40)]
    result = run_cli(make_config(server.url, rpm=600), rows)
    assert result.exit_code == 0
    assert len(result.rows) == 40
    assert result.summary["throughput_rpm"] >= 0.8 * 600


# Spec: "A sequential client will leave capacity idle" -- 40 rows against a
# 4-wide server taking 0.4s each must finish in roughly 4s, not 16s.
def test_run_is_not_sequential(servers, run_cli):
    server = servers(contents=["#### 8"], service_time=0.4, workers=4)
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(40)]
    result = run_cli(make_config(server.url, rpm=600), rows)
    assert result.summary["elapsed_seconds"] < 8.0


# Spec: "keep enough requests in flight to use the configured request budget
# effectively" -- rejection attempts of different rows also overlap.
def test_rejection_rows_overlap(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.3, workers=4)
    config = make_config(
        server.url,
        rpm=600,
        generation={"scheme": "rejection", "temperature": 0.7, "n": 2},
    )
    rows = [{"question": f"q{i}", "answer": "8"} for i in range(10)]
    result = run_cli(config, rows)
    # 20 attempts, 2 sequential per row: >= 0.6s, but well under the 6s a
    # fully sequential client would need.
    assert result.summary["elapsed_seconds"] < 3.0
    assert result.summary["total_api_calls"] == 20

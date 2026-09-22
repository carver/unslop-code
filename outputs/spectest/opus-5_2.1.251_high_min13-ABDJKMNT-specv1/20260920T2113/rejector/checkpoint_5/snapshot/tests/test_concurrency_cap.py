"""`max_concurrent`: the hard cap on in-flight requests."""

from __future__ import annotations

from tests.conftest import (
    agentic_config, answering, lookup_then_answer, numbered_rows, task_config,
)


# "`max_concurrent` is a hard cap on in-flight requests independent of RPM and TPM"
def test_in_flight_requests_never_exceed_the_cap(cli, api):
    server = api(answering(), delay=0.1)
    config = task_config(api_url=server.url, rpm=6000,
                         rate_limits={"max_concurrent": 3})
    run = cli.run(config, numbered_rows(15))
    assert run.returncode == 0
    assert server.log.max_in_flight <= 3
    assert len(run.rows) == 15


# "`max_concurrent` is a hard cap ... independent of RPM" - a high request budget
# does not lift it
def test_cap_holds_against_a_high_request_budget(cli, api):
    server = api(answering(), delay=0.1)
    config = task_config(api_url=server.url, rpm=6000,
                         rate_limits={"max_concurrent": 1})
    run = cli.run(config, numbered_rows(6))
    assert run.returncode == 0
    assert server.log.max_in_flight == 1


# "`max_concurrent` is a hard cap ... independent of ... TPM" - a generous token
# budget does not lift it either
def test_cap_holds_against_a_high_token_budget(cli, api):
    server = api(answering(), delay=0.1)
    config = task_config(api_url=server.url, rpm=6000,
                         rate_limits={"max_concurrent": 2, "tpm": 1000000})
    run = cli.run(config, numbered_rows(8))
    assert run.returncode == 0
    assert server.log.max_in_flight <= 2


# "without `max_concurrent`" the earlier in-flight behaviour is unchanged: a slow
# server still sees overlapping requests
def test_requests_still_overlap_without_a_cap(cli, api):
    server = api(answering(), delay=0.2)
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10))
    assert run.returncode == 0
    assert server.log.max_in_flight > 1


# "rows are still paired with outputs in input order even when requests overlap"
def test_rows_keep_input_order_under_the_cap(cli, api):
    server = api(answering(), delay=0.02)
    config = task_config(api_url=server.url, rpm=600, rate_limits={"max_concurrent": 4})
    run = cli.run(config, numbered_rows(12))
    assert run.returncode == 0
    assert [row["input"]["question"] for row in run.rows] == [str(n) for n in range(12)]
    for row in run.rows:
        assert row["output"]["solution"] == f"#### {row['input']['question']}"


# "for agentic loops, every API request counts toward RPM and TPM, and the loop
#  holds one concurrency slot for its entire lifetime"
def test_agentic_loop_keeps_its_slot_across_iterations(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", "#### 1250000"), delay=0.05)
    config = agentic_config(api_url=server.url, rate_limits={"max_concurrent": 1})
    rows = [{"question": "alpha", "answer": "1250000"},
            {"question": "beta", "answer": "1250000"}]
    run = cli.run(config, rows)
    assert run.returncode == 0
    # Each loop makes two requests; holding the slot keeps them together instead
    # of letting the other row slip in between.
    asked = [body["messages"][1]["content"] for body in server.log.bodies]
    assert asked == ["alpha", "alpha", "beta", "beta"]
    assert server.log.max_in_flight == 1


# "for agentic loops, every API request counts toward RPM and TPM" - both of a
# loop's requests are paced, so a loop under a cap never overlaps itself
def test_every_agentic_request_goes_through_the_limiter(cli, api):
    server = api(lookup_then_answer("revenue_q1", "1250000", "#### 1250000"), delay=0.05)
    config = agentic_config(api_url=server.url, rpm=600,
                            rate_limits={"max_concurrent": 2, "tpm": 500000})
    run = cli.run(config, [{"question": f"q{index}", "answer": "1250000"}
                           for index in range(6)])
    assert run.returncode == 0
    assert len(server.log.calls) == 12
    assert server.log.max_in_flight <= 2

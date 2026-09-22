"""Concurrency: the tool must use the configured request budget."""

from __future__ import annotations

from tests.conftest import task_config
from tests.fake_api import ok


def echo_responder(index, body):
    question = body["messages"][-1]["content"]
    return ok(f"#### {question}")


def rows_for(count):
    return [{"question": str(value), "answer": str(value)} for value in range(count)]


# "The tool must issue requests concurrently." / "A sequential client will leave
#  capacity idle"
def test_requests_overlap_in_flight(cli, api):
    server = api(echo_responder, delay=0.3)
    run = cli.run(task_config(api_url=server.url, rpm=600), rows_for(20))
    assert run.returncode == 0
    assert server.log.max_in_flight > 1


# "Target at least 80% of the configured rpm."
def test_throughput_reaches_eighty_percent_of_rpm(cli, api):
    rpm = 600
    server = api(echo_responder, delay=0.25)
    run = cli.run(task_config(api_url=server.url, rpm=rpm), rows_for(60))
    assert run.returncode == 0
    assert run.summary["throughput_rpm"] >= 0.8 * rpm


# "your tool should keep enough requests in flight to use the configured request
#  budget effectively" - a slow server must not serialise the run
def test_wall_clock_beats_a_sequential_pipeline(cli, api):
    delay = 0.2
    count = 30
    server = api(echo_responder, delay=delay)
    run = cli.run(task_config(api_url=server.url, rpm=600), rows_for(count))
    assert run.returncode == 0
    assert run.summary["elapsed_seconds"] < count * delay / 2


# "Send requests in input order: concurrent execution must not cause a later
#  input row to consume the response intended for an earlier row."
# Arrival order at the server cannot be asserted exactly - concurrent TCP
# connects race - so this checks the invariant that matters: every row is sent
# exactly once and keeps its own response (T20).
def test_every_row_is_sent_once_and_keeps_its_own_response(cli, api):
    server = api(echo_responder, delay=0.05)
    rows = rows_for(25)
    run = cli.run(task_config(api_url=server.url, rpm=600), rows)
    assert run.returncode == 0
    assert sorted(server.log.user_prompts) == sorted(row["question"] for row in rows)
    for row in run.rows:
        assert row["output"]["solution"] == f"#### {row['input']['question']}"


# "Send requests in input order" - the rate limiter admits waiters in the order
# they arrived, so rows are dispatched in input order.
def test_rate_limiter_admits_waiters_in_arrival_order():
    import asyncio

    from rejlib.ratelimit import RateLimiter

    async def scenario():
        limiter = RateLimiter(rpm=6000)  # 10ms apart, so waiters must queue
        admitted = []

        async def waiter(index):
            await limiter.acquire()
            admitted.append(index)

        await asyncio.gather(*(waiter(index) for index in range(12)))
        return admitted

    assert asyncio.run(scenario()) == list(range(12))


# "rejection" attempts are concurrent across rows as well
def test_rejection_rows_run_concurrently(cli, api):
    server = api(lambda index, body: ok("#### -1"), delay=0.2)  # no row expects -1
    config = task_config(
        api_url=server.url, rpm=600,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 2},
    )
    run = cli.run(config, rows_for(10))
    assert run.returncode == 0
    assert len(server.log.calls) == 20
    assert server.log.max_in_flight > 1
    assert run.summary["elapsed_seconds"] < 20 * 0.2 / 2

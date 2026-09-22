"""Budget exhaustion: stopping cleanly and reporting partial output."""

from __future__ import annotations

import pytest

from tests.conftest import answering, numbered_rows, task_config

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
USAGE = {"prompt_tokens": 1000, "completion_tokens": 500}
#: What one reply of ``USAGE`` costs at ``RATES``.
PER_CALL = 0.025
#: Budgets between two whole calls, so no comparison lands on a float boundary.
AFTER_ONE = 0.02
AFTER_TWO = 0.04
AFTER_THREE = 0.06


def budget_run(cli, api, rows, budget, **overrides):
    """A sequential run (one request at a time) with a budget, so the row the
    budget stops is unambiguous."""
    server = api(answering(**USAGE))
    config = task_config(
        api_url=server.url, rpm=600, rate_limits={"max_concurrent": 1},
        cost={**RATES, "budget": budget}, **overrides,
    )
    return server, cli.run(config, rows)


# "when `budget` is configured and the running total reaches or exceeds it: stop
#  sending new requests immediately"
def test_no_request_is_sent_after_the_budget_is_reached(cli, api):
    server, run = budget_run(cli, api, numbered_rows(10), AFTER_TWO)
    assert run.returncode == 0
    assert len(server.log.calls) == 2


# "let in-flight requests finish, write completed results"
def test_completed_rows_are_written(cli, api):
    server, run = budget_run(cli, api, numbered_rows(10), AFTER_TWO)
    assert [row["input"]["question"] for row in run.rows] == ["0", "1"]
    assert run.rows[0]["output"]["solution"] == "#### 0"


# "budget exhaustion is not an error; partial output is valid" / "exit `0`"
def test_budget_exhaustion_exits_zero(cli, api):
    server, run = budget_run(cli, api, numbered_rows(10), AFTER_ONE)
    assert run.returncode == 0
    assert run.stderr == ""
    assert len(run.rows) < 10


# "print the summary" - the summary covers the rows that were written
def test_summary_counts_only_completed_rows(cli, api):
    server, run = budget_run(cli, api, numbered_rows(10), AFTER_THREE)
    assert run.summary["total"] == 3
    assert run.summary["passed"] == 3


# "if `budget: 1.00` and the running total reaches `$1.02` ... print
#  `cost.budget_exceeded: true`"
def test_budget_exceeded_is_reported(cli, api):
    server, run = budget_run(cli, api, numbered_rows(10), AFTER_TWO)
    cost = run.summary["cost"]
    assert cost["budget_exceeded"] is True
    assert cost["total"] >= cost["budget"]
    assert cost["budget_remaining"] <= 0


# "the running total reaches or exceeds it" - a total that overshoots still stops
# the run and reports the overshoot
def test_overshooting_the_budget_is_reported_not_clamped(cli, api):
    server, run = budget_run(cli, api, numbered_rows(10), 0.03)  # 1.2 calls' worth
    cost = run.summary["cost"]
    assert cost["total"] == pytest.approx(2 * PER_CALL)
    assert cost["budget_remaining"] == pytest.approx(0.03 - 2 * PER_CALL)
    assert cost["budget_exceeded"] is True


# "when `budget` is configured and the running total reaches or exceeds it" - a
# budget the run stays under changes nothing
def test_run_under_budget_is_unaffected(cli, api):
    server, run = budget_run(cli, api, numbered_rows(4), 10.0)
    assert len(run.rows) == 4
    assert run.summary["cost"]["budget_exceeded"] is False


# "stop sending new requests immediately" - a rejection row stops attempting too,
# so the two calls the budget allows are the first row's first two attempts
def test_rejection_attempts_stop_at_the_budget(cli, api):
    from tests.fake_api import ok

    server = api(lambda index, body: ok("#### -1", **USAGE))  # no row expects -1
    config = task_config(
        api_url=server.url, rpm=600, rate_limits={"max_concurrent": 1},
        cost={**RATES, "budget": AFTER_TWO},
        generation={"scheme": "rejection", "temperature": 0.8, "n": 3},
    )
    run = cli.run(config, numbered_rows(6))
    assert run.returncode == 0
    assert len(server.log.calls) == 2
    assert [row["input"]["question"] for row in run.rows] == ["0"]
    assert run.rows[0]["result"]["attempts"] == 2


# "if no cost configuration is present" there is no budget to exhaust
def test_without_a_budget_every_row_runs(cli, api):
    server = api(answering(**USAGE))
    config = task_config(api_url=server.url, rpm=600, cost=RATES)
    run = cli.run(config, numbered_rows(6))
    assert len(run.rows) == 6
    assert run.summary["cost"]["budget"] is None
    assert run.summary["cost"]["budget_exceeded"] is False

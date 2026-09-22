"""Cost accounting: per-call pricing, the summary block, and the budget."""

from __future__ import annotations

from conftest import agentic_config, make_config
from mock_server import Reply

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
ROWS = [{"question": f"q{index}", "answer": "1"} for index in range(4)]


def priced_config(server_url, budget=None, **overrides):
    """A greedy task with the spec's example cost rates."""
    cost = dict(RATES)
    if budget is not None:
        cost["budget"] = budget
    return make_config(server_url, cost=cost, **overrides)


# Spec: "(prompt_tokens / 1000 * prompt_cost_per_1k) + (completion_tokens /
# 1000 * completion_cost_per_1k)" per API call.
def test_cost_per_call_uses_the_configured_rates(servers, run_cli):
    server = servers(prompt_tokens=2000, completion_tokens=500)
    result = run_cli(priced_config(server.url), ROWS[:1])
    assert result.exit_code == 0, result.stderr
    assert result.summary["cost"]["prompt"] == 0.02
    assert result.summary["cost"]["completion"] == 0.015
    assert result.summary["cost"]["total"] == 0.035


# Spec: "track prompt cost, completion cost, and total cost across all tasks".
def test_costs_accumulate_over_every_call(servers, run_cli):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    result = run_cli(priced_config(server.url), ROWS)
    assert result.summary["cost"]["prompt"] == 0.04
    assert result.summary["cost"]["completion"] == 0.12
    assert result.summary["cost"]["total"] == 0.16


# Spec: "include judge calls and every agentic iteration" -- the judge call.
def test_judge_calls_are_charged(servers, run_cli):
    server = servers(
        contents=["an answer"],
        content_if_contains={"judge": "9"},
        prompt_tokens=1000,
        completion_tokens=1000,
    )
    config = priced_config(
        server.url,
        prompt={"user": "{question}"},
        evaluation={
            "type": "llm_judge",
            "judge_prompt": {"system": "judge", "user": "Score {__response__}"},
            "threshold": 7,
        },
    )
    result = run_cli(config, ROWS[:1])
    assert result.exit_code == 0, result.stderr
    assert result.summary["total_api_calls"] == 2
    assert result.summary["cost"]["total"] == 0.08


# Spec: "include judge calls and every agentic iteration" -- each iteration of
# a loop is its own charged request.
def test_every_agentic_iteration_is_charged(servers, run_cli):
    lookup = Reply(tool_calls=[{"name": "lookup", "arguments": {"key": "employees"}}])
    server = servers(
        responder=lambda payload, path, index: (
            Reply(content="142") if _has_tool_turn(payload) else lookup
        ),
        prompt_tokens=1000,
        completion_tokens=1000,
    )
    config = agentic_config(server.url, cost=dict(RATES))
    result = run_cli(config, [{"question": "How many?", "answer": "142"}])
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["result"]["iterations"] == 2
    assert result.summary["cost"]["total"] == 0.08


def _has_tool_turn(payload: dict) -> int:
    return sum(1 for message in payload["messages"] if message.get("tool_calls"))


# Spec: the summary's cost block, including `budget` and `budget_remaining`.
def test_summary_cost_shape(servers, run_cli):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    result = run_cli(priced_config(server.url, budget=50.0), ROWS[:1])
    assert result.summary["cost"] == {
        "total": 0.04,
        "prompt": 0.01,
        "completion": 0.03,
        "budget": 50.0,
        "budget_remaining": 49.96,
        "budget_exceeded": False,
    }


# Spec: "if no cost configuration is present, omit the `cost` field from the
# summary."
def test_summary_omits_cost_without_cost_config(server, run_cli):
    result = run_cli(make_config(server.url), ROWS[:1])
    assert result.exit_code == 0, result.stderr
    assert "cost" not in result.summary


# Spec: "when `budget` is configured and the running total reaches or exceeds
# it: stop sending new requests immediately, let in-flight requests finish,
# write completed results, print the summary, and exit `0`" -- with one request
# in flight at a time, the fourth call is the one that crosses $0.1.
def test_budget_stops_the_run_and_exits_zero(servers, run_cli):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    config = priced_config(
        server.url, budget=0.1, rate_limits={"max_concurrent": 1}
    )
    rows = [{"question": f"q{index}", "answer": "1"} for index in range(20)]
    result = run_cli(config, rows)
    assert result.exit_code == 0
    assert server.call_count == 3
    assert len(result.rows) == 3
    assert result.summary["total"] == 3
    assert result.summary["cost"]["budget_exceeded"] is True
    assert result.summary["cost"]["total"] == 0.12


# Spec: "budget exhaustion is not an error; partial output is valid" -- the
# rows that did finish are complete, well-formed result rows.
def test_partial_output_is_valid(servers, run_cli):
    server = servers(prompt_tokens=1000, completion_tokens=1000, contents=["#### 1"])
    config = priced_config(
        server.url, budget=0.1, rate_limits={"max_concurrent": 1}
    )
    rows = [{"question": f"q{index}", "answer": "1"} for index in range(20)]
    result = run_cli(config, rows)
    assert [row["input"] for row in result.rows] == rows[:3]
    assert all(row["result"]["passed"] is True for row in result.rows)
    assert not result.stderr.strip()


# Spec: "budget_exceeded" stays false on a run that stays inside its budget.
def test_budget_not_exceeded_when_the_run_fits(servers, run_cli):
    server = servers(prompt_tokens=1000, completion_tokens=1000)
    result = run_cli(priced_config(server.url, budget=50.0), ROWS)
    assert result.summary["cost"]["budget_exceeded"] is False
    assert result.summary["cost"]["budget_remaining"] == 49.84
    assert len(result.rows) == 4

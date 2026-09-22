"""Cost accounting and the run's spend budget."""

import pytest

from config import CostConfig
from helpers import load_multi

COST = """  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
"""


def cost_config(url, *, cost=COST, rows_per_minute=600):
    """A greedy task config carrying the caller's ``cost`` block."""
    return f"""
task:
  name: "priced"
  api_url: "{url}"
  model: "mock-model"
  rate_limits:
    rpm: {rows_per_minute}
    max_concurrent: 1
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 32
  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
{cost}  output_field: "solution"
"""


def rows(count):
    return [{"question": f"what is question {index}", "answer": "8"} for index in range(count)]


def test_cost_is_reported_per_component(mock_server, run_cli):
    server = mock_server()

    completed, summary, results = run_cli(cost_config(server.url), rows(3))

    assert completed.returncode == 0, completed.stderr
    assert len(results) == 3
    cost = summary["cost"]
    assert cost["prompt"] > 0 and cost["completion"] > 0
    assert cost["total"] == pytest.approx(cost["prompt"] + cost["completion"], abs=0.0001)
    tokens = summary["total_prompt_tokens"] / 1000 * 0.01
    assert cost["prompt"] == round(tokens, 4)
    assert "budget" not in cost


def test_no_cost_configuration_omits_the_cost_field(mock_server, run_cli):
    server = mock_server()

    _, summary, _ = run_cli(cost_config(server.url, cost=""), rows(2))

    assert "cost" not in summary


def test_budget_reports_what_is_left(mock_server, run_cli):
    server = mock_server()
    config = cost_config(server.url, cost=COST + "    budget: 50.0\n")

    _, summary, results = run_cli(config, rows(2))

    cost = summary["cost"]
    assert len(results) == 2
    assert cost["budget"] == 50.0
    assert cost["budget_remaining"] == round(50.0 - cost["total"], 4)
    assert cost["budget_exceeded"] is False


def test_an_exhausted_budget_stops_the_run_but_keeps_its_results(mock_server, run_cli):
    server = mock_server()
    config = cost_config(server.url, cost=COST + "    budget: 0.0001\n")

    completed, summary, results = run_cli(config, rows(6))

    assert completed.returncode == 0, completed.stderr
    assert 0 < len(results) < 6
    assert summary["total"] == len(results)
    assert summary["cost"]["budget_exceeded"] is True
    assert summary["cost"]["total"] >= 0.0001


def test_the_budget_flag_overrides_the_configured_budget(mock_server, run_cli):
    server = mock_server()
    config = cost_config(server.url, cost=COST + "    budget: 50.0\n")

    _, summary, results = run_cli(config, rows(6), "--budget", "0.0001")

    assert summary["cost"]["budget"] == 0.0001
    assert summary["cost"]["budget_exceeded"] is True
    assert len(results) < 6


def test_judge_calls_are_charged_too(mock_server, run_cli):
    server = mock_server("--judge-score", "8")
    judged = f"""
task:
  name: "judged"
  api_url: "{server.url}"
  model: "mock-model"
  rate_limits:
    rpm: 600
  prompt:
    user: "{{question}}"
  generation:
    scheme: "greedy"
    max_tokens: 32
  evaluation:
    type: "llm_judge"
    judge_prompt:
      system: "You are a judge. Reply with one integer."
      user: "Rate: {{__response__}}"
    threshold: 7
{COST}  output_field: "solution"
"""

    _, summary, results = run_cli(judged, rows(1))

    judge_tokens = results[0]["meta"]["judge_meta"]["prompt_tokens"]
    assert summary["total_api_calls"] == 2
    assert judge_tokens > 0
    charged = summary["total_prompt_tokens"] + judge_tokens
    assert summary["cost"]["prompt"] == round(charged / 1000 * 0.01, 4)


def test_per_task_cost_overrides_only_the_keys_it_names(tmp_path):
    tasks = load_multi(tmp_path)

    assert tasks["gsm8k"].cost == CostConfig(
        prompt_per_1k=0.01, completion_per_1k=0.03, budget=50.0
    )
    assert tasks["code_gen"].cost == CostConfig(
        prompt_per_1k=0.005, completion_per_1k=0.03, budget=50.0
    )

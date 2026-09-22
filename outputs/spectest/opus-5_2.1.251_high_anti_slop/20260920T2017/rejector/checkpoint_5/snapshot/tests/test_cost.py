"""Charging API calls to a budget, and the summary that reports them."""

import pytest

from config import CostConfig, PromptConfig, GenerationConfig, RateLimits, TaskConfig
from cost import BudgetExhausted, CostTracker, tracker_for

RATES = CostConfig(prompt_cost_per_1k=0.01, completion_cost_per_1k=0.03, budget=50.0)


def make_task(cost=None):
    return TaskConfig(
        name="t",
        api_url="http://localhost:8000",
        model="gpt-4",
        rate_limits=RateLimits(rpm=60),
        prompt=PromptConfig(system="s", user="{question}"),
        generation=GenerationConfig("greedy", 0.0, 256, n=1, max_attempts=3),
        evaluation=None,
        output_field="solution",
        cost=cost,
    )


def test_a_call_costs_its_prompt_and_completion_tokens():
    tracker = CostTracker()
    tracker.charge(RATES, prompt_tokens=1000, completion_tokens=2000)
    assert (tracker.prompt, tracker.completion) == (0.01, 0.06)
    assert tracker.total == pytest.approx(0.07)


def test_costs_accumulate_across_calls_and_tasks():
    tracker = CostTracker()
    for _ in range(3):
        tracker.charge(RATES, prompt_tokens=500, completion_tokens=500)
    assert tracker.total == pytest.approx(0.06)


def test_a_run_without_a_budget_is_never_exceeded():
    tracker = CostTracker()
    tracker.charge(RATES, prompt_tokens=10**6, completion_tokens=10**6)
    assert tracker.exceeded is False
    tracker.check()


def test_the_budget_stops_further_requests_once_reached():
    tracker = CostTracker(budget=0.05)
    tracker.charge(RATES, prompt_tokens=1000, completion_tokens=1000)
    tracker.check()

    tracker.charge(RATES, prompt_tokens=1000, completion_tokens=1000)
    assert tracker.exceeded is True
    with pytest.raises(BudgetExhausted):
        tracker.check()


def test_the_summary_reports_what_is_left_of_the_budget():
    tracker = CostTracker(budget=50.0, configured=True)
    tracker.charge(RATES, prompt_tokens=450_000, completion_tokens=265_000)
    assert tracker.summary() == {
        "total": 12.45,
        "prompt": 4.5,
        "completion": 7.95,
        "budget": 50.0,
        "budget_remaining": 37.55,
        "budget_exceeded": False,
    }


def test_a_run_tracks_cost_only_when_a_task_configures_it():
    assert tracker_for([make_task(), make_task()]).configured is False
    assert tracker_for([make_task(), make_task(RATES)]).configured is True


def test_the_run_budget_is_the_lowest_any_task_sets():
    lower = CostConfig(budget=10.0)
    assert tracker_for([make_task(RATES), make_task(lower)]).budget == 10.0
    assert tracker_for([make_task(CostConfig())]).budget is None

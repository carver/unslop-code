"""Per-call cost, the running total and the budget that stops a run."""

from cost import CostConfig, CostTracker, build_tracker

RATES = CostConfig(prompt_per_1k=0.01, completion_per_1k=0.03)


def test_a_call_is_priced_per_thousand_tokens():
    tracker = CostTracker(configured=True)
    tracker.record(RATES, prompt_tokens=1000, completion_tokens=500)
    assert (tracker.prompt, tracker.completion, tracker.total) == (0.01, 0.015, 0.025)


def test_a_task_without_prices_spends_nothing():
    tracker = CostTracker(configured=True)
    tracker.record(None, prompt_tokens=10_000, completion_tokens=10_000)
    assert tracker.total == 0.0


def test_the_budget_is_exhausted_once_it_is_reached():
    tracker = CostTracker(budget=1.0, configured=True)
    tracker.record(CostConfig(prompt_per_1k=1.0), prompt_tokens=999, completion_tokens=0)
    assert tracker.exhausted is False

    tracker.record(CostConfig(prompt_per_1k=1.0), prompt_tokens=2, completion_tokens=0)
    assert tracker.exhausted is True


def test_an_unbudgeted_run_is_never_exhausted():
    tracker = CostTracker(configured=True)
    tracker.record(RATES, prompt_tokens=10**9, completion_tokens=10**9)
    assert tracker.exhausted is False
    assert tracker.summary()["budget"] is None


def test_the_summary_reports_the_split_and_what_is_left():
    tracker = CostTracker(budget=50.0, configured=True)
    tracker.record(RATES, prompt_tokens=450_000, completion_tokens=265_000)
    assert tracker.summary() == {
        "total": 12.45,
        "prompt": 4.5,
        "completion": 7.95,
        "budget": 50.0,
        "budget_remaining": 37.55,
        "budget_exceeded": False,
    }


def test_an_uncosted_run_reports_no_cost_at_all():
    assert build_tracker([None, None]).summary() is None


def test_the_run_takes_the_tightest_budget_any_task_sets():
    tracker = build_tracker([CostConfig(budget=20.0), CostConfig(budget=5.0), None])
    assert (tracker.budget, tracker.configured) == (5.0, True)

"""Cost Tracking section: rates, totals, and the budget stop."""

import pytest

import fake_api

# One call with these usage numbers costs, at the default example rates,
#   prompt:     100/1000 * 0.01 = 0.001
#   completion: 200/1000 * 0.03 = 0.006
#   total:                        0.007
USAGE = {"prompt_tokens": 100, "completion_tokens": 200}
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def priced(content="#### 5"):
    return fake_api.always(content, **USAGE)


# ---------------------------------------------------------------------------
# Spec: "defaults: cost: {prompt_cost_per_1k, completion_cost_per_1k, budget}"
# Context: Cost Tracking.  The summary gains a `cost` object of this shape.
# ---------------------------------------------------------------------------
def test_summary_cost_shape(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES, budget=50.0)}, check=0)
    cost = res.summary["cost"]
    assert set(cost) == {"total", "prompt", "completion", "budget",
                         "budget_remaining", "budget_exceeded"}
    assert cost["budget"] == 50.0
    assert cost["budget_exceeded"] is False


# ---------------------------------------------------------------------------
# Spec: "(prompt_tokens / 1000 * prompt_cost_per_1k) +
#        (completion_tokens / 1000 * completion_cost_per_1k)"
# Context: Cost Tracking.  Exact arithmetic for one call.
# ---------------------------------------------------------------------------
def test_cost_per_api_call_formula(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES)}, check=0)
    cost = res.summary["cost"]
    assert cost["prompt"] == pytest.approx(0.001)
    assert cost["completion"] == pytest.approx(0.006)
    assert cost["total"] == pytest.approx(0.007)


# ---------------------------------------------------------------------------
# Spec: "track prompt cost, completion cost, and total cost across all tasks"
# Context: Cost Tracking.  Several rows accumulate.
# ---------------------------------------------------------------------------
def test_cost_accumulates_over_rows(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(5)]
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES)}, rows=rows, check=0)
    assert res.summary["cost"]["total"] == pytest.approx(0.035)


# ---------------------------------------------------------------------------
# Spec: "For multi-task configs, `defaults.cost` is merged into each task the
#        same way earlier checkpoints merged `prompt`, `generation`, and
#        `evaluation`."
# Context: Cost Tracking.  Both tasks are priced, and the total spans tasks.
# ---------------------------------------------------------------------------
def test_defaults_cost_merges_into_every_task(run_multi):
    with fake_api.FakeAPI(priced("B")) as api:
        res = run_multi(api, defaults={"cost": dict(RATES)}, check=0)
    assert res.summary["cost"]["total"] == pytest.approx(0.014)


# ---------------------------------------------------------------------------
# Spec: "Per-task `cost` keys override only the keys they specify."
# Context: Cost Tracking.  gsm8k is half price, mmlu keeps the defaults.
# ---------------------------------------------------------------------------
def test_per_task_cost_overrides(run_multi):
    with fake_api.FakeAPI(priced("B")) as api:
        res = run_multi(api,
                        defaults={"cost": dict(RATES, budget=50.0)},
                        tasks={"gsm8k": {"cost": {
                            "prompt_cost_per_1k": 0.005,
                            "completion_cost_per_1k": 0.015}}},
                        check=0)
    cost = res.summary["cost"]
    assert cost["prompt"] == pytest.approx(0.0005 + 0.001)
    assert cost["completion"] == pytest.approx(0.003 + 0.006)
    assert cost["total"] == pytest.approx(0.0105)
    assert cost["budget"] == 50.0


# ---------------------------------------------------------------------------
# Spec: "CLI flag: --budget <float>"
# Context: Cost Tracking.  The flag supplies a budget the config lacks.
# ---------------------------------------------------------------------------
def test_budget_cli_flag(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES)},
                       extra=["--budget", "2.5"], check=0)
    assert res.summary["cost"]["budget"] == 2.5


def test_budget_cli_flag_overrides_the_config(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES, budget=50.0)},
                       extra=["--budget", "9.0"], check=0)
    assert res.summary["cost"]["budget"] == 9.0


# ---------------------------------------------------------------------------
# Spec: "budget_remaining"
# Context: Cost Tracking.  budget minus the running total.
# ---------------------------------------------------------------------------
def test_budget_remaining(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(3)]
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES, budget=50.0)},
                       rows=rows, check=0)
    cost = res.summary["cost"]
    assert cost["total"] == pytest.approx(0.021)
    assert cost["budget_remaining"] == pytest.approx(50.0 - 0.021)


# ---------------------------------------------------------------------------
# Spec: "include judge calls and every agentic iteration"
# Context: Cost Tracking.  An llm_judge row bills two calls.
# ---------------------------------------------------------------------------
def test_judge_calls_are_billed(run_task):
    judge = fake_api.dispatch(
        lambda rec: "Rate" in (rec.system_content or ""),
        fake_api.always("0.9", **USAGE), fake_api.always("#### 5", **USAGE))
    with fake_api.FakeAPI(judge) as api:
        res = run_task(api,
                       task={"cost": dict(RATES),
                             "evaluation": {
                                 "type": "llm_judge",
                                 "answer_field": None, "extract": None,
                                 "judge_prompt": {
                                     "system": "Rate the answer 0..1.",
                                     "user": "{question} -> {__response__}"},
                                 "threshold": 0.5}},
                       check=0)
    assert api.call_count == 2
    assert res.summary["cost"]["total"] == pytest.approx(0.014)


# ---------------------------------------------------------------------------
# Spec: "include judge calls and every agentic iteration"
# Context: Cost Tracking.  A three-request loop bills three calls.
# ---------------------------------------------------------------------------
def test_every_agentic_iteration_is_billed(run_agentic):
    script = [fake_api.calls(("lookup", {"key": "revenue_q1"}), **USAGE),
              fake_api.calls(("lookup", {"key": "revenue_q2"}), **USAGE),
              fake_api.final("#### 2730000", **USAGE)]
    with fake_api.FakeAPI(fake_api.agentic(script)) as api:
        res = run_agentic(api, task={"cost": dict(RATES)}, check=0)
    assert api.call_count == 3
    assert res.summary["cost"]["total"] == pytest.approx(0.021)


# ---------------------------------------------------------------------------
# Spec: "if no cost configuration is present, omit the `cost` field from the
#        summary"
# Context: Cost Tracking.  Earlier checkpoints' summaries are unchanged.
# ---------------------------------------------------------------------------
def test_cost_field_absent_without_cost_configuration(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, check=0)
    assert "cost" not in res.summary


# ---------------------------------------------------------------------------
# Spec: "when `budget` is configured and the running total reaches or exceeds
#        it: stop sending new requests immediately, let in-flight requests
#        finish, write completed results, print the summary, and exit `0`"
# Context: Cost Tracking.  One slot, $0.007 a row, a $0.01 budget: the third
# row is never dispatched.
# ---------------------------------------------------------------------------
def test_budget_stops_new_requests(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(10)]
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api,
                       task={"cost": dict(RATES, budget=0.01),
                             "rate_limits": {"max_concurrent": 1}},
                       rows=rows, check=0)
    assert api.call_count == 2
    assert len(res.rows) == 2
    assert [r["input"]["question"] for r in res.rows] == ["q0", "q1"]
    assert res.summary["total"] == 2
    assert res.summary["cost"]["budget_exceeded"] is True
    assert res.summary["cost"]["total"] == pytest.approx(0.014)


# ---------------------------------------------------------------------------
# Spec: "budget exhaustion is not an error; partial output is valid"
# Context: Cost Tracking.  Exit code 0 and a shorter output file.
# ---------------------------------------------------------------------------
def test_budget_exhaustion_exits_zero_with_partial_output(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(20)]
    with fake_api.FakeAPI(priced(), latency=0.02) as api:
        res = run_task(api,
                       task={"cost": dict(RATES, budget=0.02),
                             "rate_limits": {"max_concurrent": 2}},
                       rows=rows, check=0)
    assert res.returncode == 0
    assert 0 < len(res.rows) < 20
    assert res.summary["cost"]["budget_exceeded"] is True


# ---------------------------------------------------------------------------
# Spec example: "if `budget: 1.00` and the running total reaches `$1.02` ...
#               print `cost.budget_exceeded: true`, exit `0`"
# Context: Cost Tracking / Examples.  budget_exceeded is False while under.
# ---------------------------------------------------------------------------
def test_budget_not_exceeded_when_under(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES, budget=1.0)}, check=0)
    assert res.summary["cost"]["budget_exceeded"] is False
    assert res.summary["cost"]["budget_remaining"] == pytest.approx(1.0 - 0.007)


# ---------------------------------------------------------------------------
# Spec: "budget" is optional; rates alone still report a cost object.
# Context: Cost Tracking.  (AMBIGUITIES T93: null budget, not omitted keys.)
# ---------------------------------------------------------------------------
def test_rates_without_budget(run_task):
    with fake_api.FakeAPI(priced()) as api:
        res = run_task(api, task={"cost": dict(RATES)}, check=0)
    cost = res.summary["cost"]
    assert cost["budget"] is None
    assert cost["budget_remaining"] is None
    assert cost["budget_exceeded"] is False


# ---------------------------------------------------------------------------
# Spec: cost values are numbers
# Context: Cost Tracking.  A malformed cost block is a configuration error.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("block", [
    {"prompt_cost_per_1k": "cheap"},
    {"budget": "free"},
    {"completion_cost_per_1k": []},
])
def test_invalid_cost_config_is_an_error(run_task, block):
    res = run_task(task={"cost": block}, check=1)
    assert "error" in res.stderr.lower()


def test_cost_must_be_a_mapping(run_task):
    res = run_task(task={"cost": 5}, check=1)
    assert "error" in res.stderr.lower()

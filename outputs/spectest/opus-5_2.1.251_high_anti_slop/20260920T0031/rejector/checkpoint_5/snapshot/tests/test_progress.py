"""The stderr progress line and when it is printed."""

import tracking
from cost import CostConfig, CostTracker
from tracking import Progress, RunMetrics


def row(passed=True):
    return {"input": {}, "output": {"solution": "x"}, "result": {"passed": passed}, "meta": None}


def metrics_for(cost=None, api_calls=6, elapsed=6.0):
    metrics = RunMetrics(cost or CostTracker())
    metrics.api_calls = api_calls
    metrics.timeline.first_request_at = 0.0
    metrics.timeline.last_response_at = elapsed
    return metrics


def lines(capsys):
    return capsys.readouterr().err.splitlines()


def test_a_line_lands_every_tenth_of_the_run(capsys):
    progress = Progress(100, evaluated=True)
    metrics = metrics_for()
    for index in range(30):
        progress.row(row(passed=index % 2 == 0), metrics)

    assert len(lines(capsys)) == 3


def test_the_line_names_counts_rate_cost_and_an_eta(capsys):
    cost = CostTracker(configured=True)
    cost.record(CostConfig(prompt_per_1k=1.0), prompt_tokens=2450, completion_tokens=0)
    progress = Progress(2, evaluated=True)
    metrics = metrics_for(cost, api_calls=6, elapsed=6.0)

    progress.row(row(passed=True), metrics)
    printed = lines(capsys)[0]

    assert printed.startswith("[1/2] 50% complete | 1 passed, 0 failed | 60.0 rpm | $2.45 spent | ETA: ")
    assert printed.endswith("s")


def test_pass_counts_are_left_out_without_evaluation(capsys):
    Progress(1, evaluated=False).row(row(), metrics_for())
    assert "passed" not in lines(capsys)[0]


def test_cost_is_left_out_when_nothing_is_priced(capsys):
    Progress(1, evaluated=True).row(row(), metrics_for())
    assert "spent" not in lines(capsys)[0]


def test_a_quiet_run_still_reports_on_the_clock(capsys, monkeypatch):
    monkeypatch.setattr(tracking, "REPORT_SECONDS", 0.0)
    progress = Progress(1000, evaluated=False)  # a tenth of the run is far away
    progress.row(row(), metrics_for())
    assert len(lines(capsys)) == 1

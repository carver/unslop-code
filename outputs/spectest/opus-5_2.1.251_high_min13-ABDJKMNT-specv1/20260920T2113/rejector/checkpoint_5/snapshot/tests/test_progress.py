"""`--progress`: the status lines written to stderr while the run proceeds."""

from __future__ import annotations

import re

from tests.conftest import answering, numbered_rows, task_config
from tests.fake_api import ok

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}

#: "[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s"
LINE = re.compile(
    r"^\[(?P<done>\d+)/(?P<total>\d+)\] (?P<percent>\d+)% complete"
    r"(?: \| (?P<passed>\d+) passed, (?P<failed>\d+) failed)?"
    r" \| (?P<rpm>\d+\.\d) rpm"
    r"(?: \| \$(?P<spent>\d+\.\d\d) spent)?"
    r" \| ETA: (?P<eta>\d+)s$"
)


def lines(run) -> list[re.Match]:
    """Every progress line the run printed, parsed."""
    printed = [line for line in run.stderr.splitlines() if line.strip()]
    matched = [LINE.match(line) for line in printed]
    assert all(matched), printed
    return matched


# "CLI flag: --progress" / "print progress updates to stderr"
def test_progress_lines_go_to_stderr(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10), "--progress")
    assert run.returncode == 0
    assert lines(run)
    assert "complete" not in run.stdout


# progress is opt-in: without the flag stderr stays quiet
def test_no_progress_without_the_flag(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10))
    assert run.stderr == ""


# "print progress updates ... every 10% of total inputs"
def test_a_line_every_ten_percent(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(20), "--progress")
    reported = [int(match["done"]) for match in lines(run)]
    assert reported[-1] == 20
    assert len(reported) >= 8


# "[50/100] 50% complete" - the counter and percentage track finished rows
def test_counter_and_percentage_advance(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10), "--progress")
    final = lines(run)[-1]
    assert (final["done"], final["total"], final["percent"]) == ("10", "10", "100")


# "include `passed` / `failed` counts only when evaluation is configured"
def test_passed_and_failed_are_reported_with_an_evaluation(cli, api):
    # rows 0-4 are answered correctly, rows 5-9 are not
    def respond(index, body):
        question = body["messages"][-1]["content"]
        return ok(f"#### {question}" if int(question) < 5 else "#### 99")

    server = api(respond)
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10), "--progress")
    final = lines(run)[-1]
    assert (final["passed"], final["failed"]) == ("5", "5")


# "if no evaluation is configured, omit the passed/failed field"
def test_passed_and_failed_are_omitted_without_an_evaluation(cli, api):
    server = api(answering())
    config = task_config(api_url=server.url, rpm=600)
    config["task"].pop("evaluation")
    run = cli.run(config, numbered_rows(10), "--progress")
    assert all(match["passed"] is None for match in lines(run))
    assert "passed" not in run.stderr


# "include `$... spent` only when cost tracking is configured"
def test_spend_is_reported_with_cost_tracking(cli, api):
    server = api(answering(prompt_tokens=1000, completion_tokens=500))
    config = task_config(api_url=server.url, rpm=600, cost=RATES)
    run = cli.run(config, numbered_rows(10), "--progress")
    final = lines(run)[-1]
    assert final["spent"] == "0.25"  # ten calls at $0.025


# "if cost tracking is disabled, omit the cost field"
def test_spend_is_omitted_without_cost_tracking(cli, api):
    server = api(answering())
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10), "--progress")
    assert all(match["spent"] is None for match in lines(run))
    assert "$" not in run.stderr


# "58.2 rpm" - the observed request rate is reported
def test_request_rate_is_reported(cli, api):
    server = api(answering(), delay=0.05)
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10), "--progress")
    assert float(lines(run)[-1]["rpm"]) > 0


# "ETA: 52s" - the estimate reaches zero as the run finishes
def test_eta_is_reported_and_ends_at_zero(cli, api):
    server = api(answering(), delay=0.02)
    run = cli.run(task_config(api_url=server.url, rpm=600), numbered_rows(10), "--progress")
    assert lines(run)[-1]["eta"] == "0"


# "print progress updates to stderr every 5 seconds ..., whichever comes first"
# - a run slower than the interval reports on the timer, not only per row
def test_slow_run_reports_on_the_timer(cli, api):
    server = api(answering(), delay=6.0)
    config = task_config(api_url=server.url, rpm=600, rate_limits={"max_concurrent": 1})
    run = cli.run(config, numbered_rows(2), "--progress")
    assert run.returncode == 0
    # two rows would report twice on row completion alone; the 5s timer adds more
    assert len(lines(run)) > 2

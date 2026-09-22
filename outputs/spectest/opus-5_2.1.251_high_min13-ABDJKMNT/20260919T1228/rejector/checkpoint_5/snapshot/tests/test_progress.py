"""`--progress`: the stderr progress line and what it contains."""

from __future__ import annotations

import json
import re

from conftest import make_config

ROWS = [{"question": f"q{index}", "answer": "1"} for index in range(10)]
LINE = re.compile(
    r"^\[(?P<done>\d+)/(?P<total>\d+)\] (?P<percent>\d+)% complete"
    r"(?P<counts> \| (?P<passed>\d+) passed, (?P<failed>\d+) failed)?"
    r" \| (?P<rpm>[\d.]+) rpm"
    r"(?P<cost> \| \$(?P<spent>[\d.]+) spent)?"
    r" \| ETA: (?P<eta>\d+)s$"
)


def progress_lines(result) -> list[re.Match]:
    matched = [LINE.match(line) for line in result.stderr.splitlines() if line.strip()]
    assert all(matched), result.stderr
    return matched


def progress_config(server_url, **overrides):
    return make_config(
        server_url,
        cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03},
        rate_limits={"max_concurrent": 2},
        **overrides,
    )


# Spec: "print progress updates to stderr every 5 seconds or every 10% of total
# inputs, whichever comes first", in the documented format.
def test_progress_lines_match_the_documented_format(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05)
    result = run_cli(progress_config(server.url), ROWS, "--progress")
    assert result.exit_code == 0, result.stderr
    lines = progress_lines(result)
    assert lines
    assert lines[-1].group("done") == "10"
    assert lines[-1].group("total") == "10"
    assert lines[-1].group("percent") == "100"


# Spec: the counts advance by at least 10% of the inputs between updates.
def test_progress_reports_at_ten_percent_steps(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05)
    result = run_cli(progress_config(server.url), ROWS, "--progress")
    done = [int(line.group("done")) for line in progress_lines(result)]
    assert done == sorted(done)
    assert len(done) >= 2


# Spec: "include `passed` / `failed` counts only when evaluation is
# configured" -- and they add up to the completed count.
def test_passed_and_failed_are_reported_with_an_evaluation(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05)
    result = run_cli(progress_config(server.url), ROWS, "--progress")
    last = progress_lines(result)[-1]
    assert int(last.group("passed")) + int(last.group("failed")) == 10
    assert last.group("passed") == "10"


# Spec: "if no evaluation is configured, omit the passed/failed field".
def test_counts_are_omitted_without_an_evaluation(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05)
    config = progress_config(server.url, evaluation=None)
    result = run_cli(config, ROWS, "--progress")
    assert all(line.group("counts") is None for line in progress_lines(result))


# Spec: "include `$... spent` only when cost tracking is configured".
def test_cost_is_reported_when_configured(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05, prompt_tokens=1000)
    result = run_cli(progress_config(server.url), ROWS, "--progress")
    assert float(progress_lines(result)[-1].group("spent")) > 0


# Spec: "if cost tracking is disabled, omit the cost field".
def test_cost_is_omitted_when_not_configured(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05)
    config = make_config(server.url)
    result = run_cli(config, ROWS, "--progress")
    assert all(line.group("cost") is None for line in progress_lines(result))


# Spec: progress goes "to stderr", so stdout still carries only the summary.
def test_progress_keeps_stdout_machine_readable(servers, run_cli):
    server = servers(contents=["#### 1"], service_time=0.05)
    result = run_cli(progress_config(server.url), ROWS, "--progress")
    assert json.loads(result.stdout)["total"] == 10

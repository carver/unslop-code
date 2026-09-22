"""`--progress`: periodic status lines on stderr."""

from __future__ import annotations

import re

from conftest import base_task
from fake_api import FakeAPI, always

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}
ROWS = [{"question": f"q{i}", "answer": "5"} for i in range(20)]

# [50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
LINE = re.compile(
    r"^\[(\d+)/(\d+)\] (\d+)% complete"
    r"(?: \| (\d+) passed, (\d+) failed)?"
    r" \| [\d.]+ rpm"
    r"(?: \| \$[\d.]+ spent)?"
    r" \| ETA: \d+s$"
)


def progress_lines(result) -> list[str]:
    return [line for line in result.stderr.splitlines() if line.startswith("[")]


# Spec: "print progress updates to stderr every 5 seconds or every 10% of
# total inputs, whichever comes first".
# Context: Progress Reporting / Rules.
def test_progress_goes_to_stderr(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        config = write_config(base_task(api.url, cost=RATES))
        result = run_cli(config, write_input(ROWS), "--progress")
    assert progress_lines(result)
    assert "% complete" not in result.stdout


# Spec: "print progress updates ... every 10% of total inputs" — twenty rows
# means an update at least every second row.
# Context: Progress Reporting / Rules.
def test_progress_reports_every_tenth_of_the_inputs(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        config = write_config(base_task(api.url))
        result = run_cli(config, write_input(ROWS), "--progress")
    assert len(progress_lines(result)) >= 5


# Spec: format "[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm |
# $2.45 spent | ETA: 52s".
# Context: Progress Reporting / Rules.
def test_progress_line_format(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        config = write_config(base_task(api.url, cost=RATES))
        result = run_cli(config, write_input(ROWS), "--progress")
    lines = progress_lines(result)
    for line in lines:
        assert LINE.match(line), line
    done, total, percent = (int(value) for value in LINE.match(lines[-1]).groups()[:3])
    assert total == 20
    assert percent == round(done / total * 100)


# Spec: "include passed / failed counts only when evaluation is configured"
# and "include $... spent only when cost tracking is configured".
# Context: Progress Reporting / Rules.
def test_progress_includes_passed_failed_and_cost(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        config = write_config(base_task(api.url, cost=RATES))
        result = run_cli(config, write_input(ROWS), "--progress")
    last = progress_lines(result)[-1]
    assert "passed," in last
    assert "$" in last


# Spec: "if no evaluation is configured, omit the passed/failed field".
# Context: Progress Reporting / Rules.
def test_progress_omits_passed_failed_without_evaluation(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        task = base_task(api.url, cost=RATES)
        task.pop("evaluation")
        config = write_config(task)
        result = run_cli(config, write_input(ROWS), "--progress")
    for line in progress_lines(result):
        assert "passed" not in line
        assert "$" in line


# Spec: "if cost tracking is disabled, omit the cost field".
# Context: Progress Reporting / Rules.
def test_progress_omits_cost_without_cost_tracking(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        config = write_config(base_task(api.url))
        result = run_cli(config, write_input(ROWS), "--progress")
    for line in progress_lines(result):
        assert "$" not in line
        assert "passed," in line


# Spec: "--progress" is opt-in.
# Context: Progress Reporting / CLI flag.
def test_no_progress_without_the_flag(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5"), slots=2, delay=0.02) as api:
        config = write_config(base_task(api.url, cost=RATES))
        result = run_cli(config, write_input(ROWS))
    assert progress_lines(result) == []

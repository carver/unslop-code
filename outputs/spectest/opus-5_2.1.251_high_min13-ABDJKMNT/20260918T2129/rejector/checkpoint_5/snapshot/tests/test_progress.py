"""`--progress`: periodic run status on stderr."""

from __future__ import annotations

import re

from fake_server import FakeAPIServer, Reply, always, completion
from conftest import base_config

LINE = re.compile(
    r"^\[(\d+)/(\d+)\] (\d+)% complete(?: \| (\d+) passed, (\d+) failed)?"
    r" \| ([\d.]+) rpm(?: \| \$([\d.]+) spent)? \| ETA: (\d+)s$"
)
RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def _rows(write_input, count=20):
    return write_input([{"question": f"q{i}", "answer": "5"} for i in range(count)])


def _lines(stderr):
    return [line for line in stderr.splitlines() if line.startswith("[")]


# Spec: "print progress updates to stderr"
def test_progress_lines_go_to_stderr(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input), "--progress")

    assert _lines(result.stderr)
    assert result.stdout.strip().startswith("{")


# Spec: format
# "[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s"
def test_progress_line_matches_the_documented_format(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5", prompt_tokens=10000, completion_tokens=20000)) as api:
        config = write_config(base_config(api.url, cost=RATES))
        result = run_cli(config, _rows(write_input), "--progress")

    for line in _lines(result.stderr):
        assert LINE.match(line), line


# Spec: "every 10% of total inputs" - the final update reports every row
def test_the_last_update_reports_completion(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input, 20), "--progress")

    last = _lines(result.stderr)[-1]
    assert last.startswith("[20/20] 100% complete")


# Spec: "include `passed` / `failed` counts only when evaluation is
# configured"
def test_passed_and_failed_appear_with_evaluation(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input, 10), "--progress")

    assert "passed" in _lines(result.stderr)[-1]


# Spec: "if no evaluation is configured, omit the passed/failed field"
def test_passed_and_failed_are_omitted_without_evaluation(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url, evaluation=None))
        result = run_cli(config, _rows(write_input, 10), "--progress")

    assert "passed" not in _lines(result.stderr)[-1]


# Spec: "include `$... spent` only when cost tracking is configured"
def test_cost_appears_when_configured(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5", prompt_tokens=10000, completion_tokens=20000)) as api:
        config = write_config(base_config(api.url, cost=RATES))
        result = run_cli(config, _rows(write_input, 10), "--progress")

    assert "spent" in _lines(result.stderr)[-1]


# Spec: "if cost tracking is disabled, omit the cost field"
def test_cost_is_omitted_when_not_configured(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input, 10), "--progress")

    assert "spent" not in _lines(result.stderr)[-1]


# Spec: progress is opt-in
def test_no_progress_output_without_the_flag(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, _rows(write_input, 10))

    assert _lines(result.stderr) == []


# Spec: "every 5 seconds or every 10% of total inputs, whichever comes
# first" - a run of 20 rows crosses ten 10% boundaries
def test_ten_percent_boundaries_trigger_updates(write_config, write_input, run_cli):
    def slow(payload, index):
        return Reply(completion("#### 5"), delay=0.02)

    with FakeAPIServer(slow, capacity=1) as api:
        config_map = base_config(api.url, rate_limits={"max_concurrent": 1})
        result = run_cli(write_config(config_map), _rows(write_input, 20), "--progress")

    assert len(_lines(result.stderr)) >= 5

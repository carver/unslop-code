"""``--dry-run`` estimates and ``--progress`` reporting."""

import json
import re

#: A port nothing listens on, so a dry run that called the API would fail loudly.
UNREACHABLE = "http://127.0.0.1:1"

COST = """  cost:
    prompt_cost_per_1k: 0.01
    completion_cost_per_1k: 0.03
"""

#: The documented progress line, e.g. ``[5/10] 50% complete | 4 passed, 1 failed | ...``.
PROGRESS_RE = re.compile(
    r"^\[(\d+)/(\d+)\] (\d+)% complete"
    r"(?: \| (\d+) passed, (\d+) failed)?"
    r" \| [\d.]+ rpm"
    r"(?: \| \$[\d.]+ spent)?"
    r" \| ETA: \d+s$"
)


def plan_config(url, *, scheme="greedy", temperature=0.0, n=1, cost=COST, evaluated=True):
    evaluation = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
""" if evaluated else ""
    return f"""
task:
  name: "planned"
  api_url: "{url}"
  model: "mock-model"
  rate_limits:
    rpm: 100
  prompt:
    user: "{{question}}"
  generation:
    scheme: "{scheme}"
    temperature: {temperature}
    max_tokens: 100
    n: {n}
{evaluation}{cost}  output_field: "solution"
"""


def rows(count):
    return [{"question": f"is question {index} four words", "answer": "8"} for index in range(count)]


def test_dry_run_estimates_without_calling_the_api(run_cli):
    completed, estimate, results = run_cli(plan_config(UNREACHABLE), rows(10), "--dry-run")

    assert completed.returncode == 0, completed.stderr
    assert results == []
    planned = estimate["tasks"]["planned"]
    assert planned == {
        "inputs": 10,
        "est_prompt_tokens": round(5 * 1.33 * 10),
        "est_completion_tokens": 1000,
        "est_total_tokens": round(5 * 1.33 * 10) + 1000,
        "est_cost": round(round(5 * 1.33 * 10) / 1000 * 0.01 + 1000 / 1000 * 0.03, 4),
    }
    assert estimate["total_inputs"] == 10
    assert estimate["est_total_tokens"] == planned["est_total_tokens"]
    assert estimate["est_total_cost"] == planned["est_cost"]
    assert estimate["est_time_minutes"] == round(10 / 100, 4)


def test_dry_run_plans_for_the_worst_case_of_rejection(run_cli):
    config = plan_config(UNREACHABLE, scheme="rejection", temperature=0.7, n=4)

    _, estimate, _ = run_cli(config, rows(10), "--dry-run")

    assert estimate["est_time_minutes"] == round(10 * 4 / 100, 4)


def test_dry_run_without_prices_estimates_no_cost(run_cli):
    _, estimate, _ = run_cli(plan_config(UNREACHABLE, cost=""), rows(4), "--dry-run")

    assert estimate["tasks"]["planned"]["est_cost"] == 0.0
    assert estimate["est_total_cost"] == 0.0


def test_dry_run_still_reports_bad_input(run_cli):
    completed, _, _ = run_cli(plan_config(UNREACHABLE), [{"answer": "8"}], "--dry-run")

    assert completed.returncode == 1
    assert "question" in completed.stderr


def test_progress_reports_every_tenth_of_the_rows(mock_server, run_cli):
    server = mock_server()

    completed, summary, _ = run_cli(plan_config(server.url), rows(10), "--progress")

    assert completed.returncode == 0, completed.stderr
    lines = completed.stderr.splitlines()
    assert len(lines) == 10
    assert all(PROGRESS_RE.match(line) for line in lines), lines
    assert lines[-1].startswith("[10/10] 100% complete")
    assert "passed," in lines[-1] and "$" in lines[-1]
    assert f"{summary['passed']} passed, {summary['failed']} failed" in lines[-1]


def test_progress_omits_fields_the_run_does_not_track(mock_server, run_cli):
    server = mock_server()
    config = plan_config(server.url, cost="", evaluated=False)

    completed, _, _ = run_cli(config, rows(10), "--progress")

    assert completed.returncode == 0, completed.stderr
    lines = completed.stderr.splitlines()
    assert all(PROGRESS_RE.match(line) for line in lines), lines
    assert all("passed" not in line and "$" not in line for line in lines)


def test_no_progress_flag_keeps_stderr_quiet(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(plan_config(server.url), rows(10))

    assert completed.stderr == ""


def test_dry_run_prints_a_plan_for_every_task(tmp_path, run_rejector):
    config = tmp_path / "multi.yaml"
    config.write_text(
        f"""
defaults:
  api_url: "{UNREACHABLE}"
  model: "mock-model"
  rate_limits:
    rpm: 100
  generation:
    max_tokens: 10
  output_field: "solution"

tasks:
  first:
    prompt:
      user: "{{question}}"
  second:
    prompt:
      user: "{{question}}"
""",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    for name in ("first", "second"):
        (data / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows(3)), encoding="utf-8"
        )

    completed = run_rejector(
        "--config", str(config), "--input-dir", str(data),
        "--output", str(tmp_path / "out"), "--dry-run",
    )

    assert completed.returncode == 0, completed.stderr
    estimate = json.loads(completed.stdout)
    assert set(estimate["tasks"]) == {"first", "second"}
    assert estimate["total_inputs"] == 6
    assert estimate["est_time_minutes"] == round(3 / 100 + 3 / 100, 4)

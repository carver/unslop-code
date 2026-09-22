"""The `--progress` lines a run prints to stderr."""

import re

TASK = {
    "name": "math_solve",
    "model": "gpt-4",
    "prompt": {"user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 64},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
    "rate_limits": {"max_concurrent": 1},
}

ROWS = [{"question": f"q{index}", "answer": "5"} for index in range(10)]

LINE = re.compile(
    r"\[(\d+)/10\] (\d+)% complete \| (\d+) passed, (\d+) failed \| [\d.]+ rpm \| ETA: \d+s"
)


def lines(stderr):
    return [line for line in stderr.splitlines() if line.startswith("[")]


def test_progress_reports_every_tenth_of_the_rows(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url}, ROWS, "--progress")

    reported = lines(run.stderr)
    assert len(reported) == 10
    assert [LINE.match(line)[1] for line in reported] == [str(number) for number in range(1, 11)]
    assert LINE.match(reported[-1]).groups()[1:4] == ("100", "10", "0")


def test_failures_are_counted_apart_from_passes(cli, api):
    wrong = ("q0", "q1", "q2")
    url, _ = api(
        lambda payload, call: "#### 7"
        if payload["messages"][-1]["content"] in wrong
        else "#### 5"
    )
    run = cli({**TASK, "api_url": url}, ROWS, "--progress")

    assert LINE.match(lines(run.stderr)[-1]).groups()[2:4] == ("7", "3")


def test_progress_is_silent_without_the_flag(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url}, ROWS)

    assert lines(run.stderr) == []


def test_spend_is_reported_when_the_task_tracks_cost(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    cost = {"prompt_cost_per_1k": 1.0, "completion_cost_per_1k": 1.0}
    run = cli({**TASK, "api_url": url, "cost": cost}, ROWS, "--progress")

    assert "$0.15 spent" in lines(run.stderr)[-1]


def test_passes_are_left_out_when_nothing_evaluates_them(cli, api):
    url, _ = api(lambda payload, call: "#### 5")
    run = cli({**TASK, "api_url": url, "evaluation": None}, ROWS, "--progress")

    last = lines(run.stderr)[-1]
    assert "passed" not in last and "spent" not in last
    assert re.fullmatch(r"\[10/10] 100% complete \| [\d.]+ rpm \| ETA: 0s", last)

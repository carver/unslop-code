"""Progress Reporting section: --progress writes updates to stderr."""

import re

import pytest

import fake_api

# [50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
LINE = re.compile(
    r"^\[(?P<done>\d+)/(?P<total>\d+)\] (?P<pct>\d+)% complete"
    r"(?: \| (?P<passed>\d+) passed, (?P<failed>\d+) failed)?"
    r" \| (?P<rpm>\d+(?:\.\d+)?) rpm"
    r"(?: \| \$(?P<cost>\d+(?:\.\d+)?) spent)?"
    r" \| ETA: (?P<eta>\d+)s$")

RATES = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def rows_of(n):
    return [{"question": "q%d" % i, "answer": "5"} for i in range(n)]


def progress_lines(res):
    return [l for l in res.stderr.splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Spec: "print progress updates to stderr every 5 seconds or every 10% of
#        total inputs, whichever comes first"
# Context: Progress Reporting.  10 rows means a line every row.
# ---------------------------------------------------------------------------
def test_progress_updates_go_to_stderr(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"rate_limits": {"max_concurrent": 1}},
                       rows=rows_of(10), extra=["--progress"], check=0)
    lines = progress_lines(res)
    assert len(lines) >= 10
    for line in lines:
        assert LINE.match(line), "bad progress line: %r" % line


# ---------------------------------------------------------------------------
# Spec: format "[50/100] 50% complete | ... | ETA: 52s"
# Context: Progress Reporting.  The counter and percentage track completions.
# ---------------------------------------------------------------------------
def test_progress_counter_and_percentage(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"rate_limits": {"max_concurrent": 1}},
                       rows=rows_of(10), extra=["--progress"], check=0)
    matches = [LINE.match(l) for l in progress_lines(res)]
    for match in matches:
        assert int(match.group("total")) == 10
        assert int(match.group("pct")) == \
            int(int(match.group("done")) * 100 / 10)
    last = matches[-1]
    assert last.group("done") == "10"
    assert last.group("pct") == "100"


# ---------------------------------------------------------------------------
# Spec: "include `passed` / `failed` counts only when evaluation is configured"
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_includes_passed_failed_with_evaluation(run_task):
    rows = [{"question": "q%d" % i, "answer": "5" if i % 2 else "9"}
            for i in range(10)]
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"rate_limits": {"max_concurrent": 1}},
                       rows=rows, extra=["--progress"], check=0)
    last = LINE.match(progress_lines(res)[-1])
    assert last.group("passed") == "5"
    assert last.group("failed") == "5"


# ---------------------------------------------------------------------------
# Spec: "if no evaluation is configured, omit the passed/failed field"
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_omits_passed_failed_without_evaluation(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"evaluation": None,
                                  "rate_limits": {"max_concurrent": 1}},
                       rows=rows_of(10), extra=["--progress"], check=0)
    for line in progress_lines(res):
        assert "passed" not in line
        assert LINE.match(line)


# ---------------------------------------------------------------------------
# Spec: "include `$... spent` only when cost tracking is configured"
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_includes_cost_when_configured(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5", prompt_tokens=1000,
                                          completion_tokens=1000)) as api:
        res = run_task(api, task={"cost": dict(RATES),
                                  "rate_limits": {"max_concurrent": 1}},
                       rows=rows_of(10), extra=["--progress"], check=0)
    last = LINE.match(progress_lines(res)[-1])
    assert last.group("cost") is not None
    assert float(last.group("cost")) == pytest.approx(0.40, abs=0.01)


# ---------------------------------------------------------------------------
# Spec: "if cost tracking is disabled, omit the cost field"
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_omits_cost_when_not_configured(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"rate_limits": {"max_concurrent": 1}},
                       rows=rows_of(10), extra=["--progress"], check=0)
    for line in progress_lines(res):
        assert "spent" not in line
        assert LINE.match(line)


# ---------------------------------------------------------------------------
# Spec: "CLI flag: --progress"
# Context: Progress Reporting.  Nothing is printed without the flag.
# ---------------------------------------------------------------------------
def test_no_progress_without_the_flag(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, rows=rows_of(10), check=0)
    assert res.stderr.strip() == ""


# ---------------------------------------------------------------------------
# Spec: "print progress updates to stderr" -- the JSON summary still owns
# stdout.
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_does_not_disturb_the_summary(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, rows=rows_of(10), extra=["--progress"], check=0)
    assert res.summary["total"] == 10
    assert res.stdout.strip().count("\n") == 0

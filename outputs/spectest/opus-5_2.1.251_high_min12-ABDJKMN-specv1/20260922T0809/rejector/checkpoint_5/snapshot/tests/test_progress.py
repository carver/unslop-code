"""Spec section: Progress Reporting (`--progress`)."""
from __future__ import annotations

import re

import pytest

from conftest import base_config, rows_of
from mock_server import MockAPI, always

# [50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm | $2.45 spent | ETA: 52s
LINE_RE = re.compile(r"^\[(\d+)/(\d+)\] (\d+)% complete \| (.*)$")
PASSED_RE = re.compile(r"(\d+) passed, (\d+) failed")
RPM_RE = re.compile(r"(\d+(?:\.\d+)?) rpm")
COST_RE = re.compile(r"\$(\d+(?:\.\d+)?) spent")
ETA_RE = re.compile(r"ETA: \S+")

COST = {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03}


def progress_lines(stderr):
    return [line for line in stderr.splitlines() if LINE_RE.match(line.strip())]


# ---------------------------------------------------------------------------
# Phrase: "print progress updates to stderr" with the documented format
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_lines_on_stderr(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.2) as api:
        cfg = write_config(base_config(
            api.url, cost=dict(COST),
            rate_limits={"max_concurrent": 1}))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, extra=["--progress"])
    assert res.returncode == 0, res
    lines = progress_lines(res.stderr)
    assert lines, res.stderr
    first = LINE_RE.match(lines[0].strip())
    done, total, percent = (int(first.group(1)), int(first.group(2)),
                            int(first.group(3)))
    assert total == 10
    assert 0 <= done <= 10
    assert percent == int(done / total * 100)
    body = first.group(4)
    assert PASSED_RE.search(body), body
    assert RPM_RE.search(body), body
    assert COST_RE.search(body), body
    assert ETA_RE.search(body), body
    # the summary is still the only thing on stdout
    assert res.summary["total"] == 10


# ---------------------------------------------------------------------------
# Phrase: "print progress updates to stderr every 5 seconds or every 10% of
#          total inputs, whichever comes first"
# Context: Progress Reporting.  Ten rows, one at a time: 10% is one row, so
# several updates must appear well before any 5-second tick.
# ---------------------------------------------------------------------------
def test_progress_updates_every_ten_percent(run_tool, write_config,
                                            write_input):
    with MockAPI(always("#### 5"), delay=0.1) as api:
        cfg = write_config(base_config(api.url,
                                       rate_limits={"max_concurrent": 1}))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, extra=["--progress"])
    assert res.returncode == 0, res
    lines = progress_lines(res.stderr)
    assert len(lines) >= 3, res.stderr


# Context: Progress Reporting - the 5-second tick fires even when no row has
# finished yet.
@pytest.mark.slow
def test_progress_ticks_every_five_seconds(run_tool, write_config,
                                           write_input):
    with MockAPI(always("#### 5"), delay=6.0) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(1))
        res = run_tool(cfg, data, extra=["--progress"], timeout=60)
    assert res.returncode == 0, res
    lines = progress_lines(res.stderr)
    assert lines, res.stderr
    # the first tick landed before the single row completed
    assert LINE_RE.match(lines[0].strip()).group(1) == "0"


# ---------------------------------------------------------------------------
# Phrase: "include `passed` / `failed` counts only when evaluation is
#          configured" / "if no evaluation is configured, omit the
#          passed/failed field"
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_omits_passed_failed_without_evaluation(run_tool,
                                                         write_config,
                                                         write_input):
    with MockAPI(always("#### 5"), delay=0.1) as api:
        cfg = write_config(base_config(api.url, evaluation=None,
                                       rate_limits={"max_concurrent": 1}))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, extra=["--progress"])
    assert res.returncode == 0, res
    lines = progress_lines(res.stderr)
    assert lines, res.stderr
    for line in lines:
        assert not PASSED_RE.search(line), line
        assert RPM_RE.search(line), line


# ---------------------------------------------------------------------------
# Phrase: "include `$... spent` only when cost tracking is configured" /
#         "if cost tracking is disabled, omit the cost field"
# Context: Progress Reporting.
# ---------------------------------------------------------------------------
def test_progress_omits_cost_without_cost_config(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 5"), delay=0.1) as api:
        cfg = write_config(base_config(api.url,
                                       rate_limits={"max_concurrent": 1}))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data, extra=["--progress"])
    assert res.returncode == 0, res
    lines = progress_lines(res.stderr)
    assert lines, res.stderr
    for line in lines:
        assert not COST_RE.search(line), line
        assert PASSED_RE.search(line), line


# ---------------------------------------------------------------------------
# Phrase: "CLI flag: --progress"
# Context: Progress Reporting.  Without the flag nothing is printed to stderr.
# ---------------------------------------------------------------------------
def test_no_progress_without_the_flag(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.05) as api:
        cfg = write_config(base_config(api.url, cost=dict(COST)))
        data = write_input(rows_of(10))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.stderr.strip() == "", res.stderr

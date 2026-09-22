"""Part 5: --progress writes periodic updates to stderr."""
import re

from conftest import cost_block, limits_block, make_config
from mock_api import MockAPI, always


ROWS = [{"question": "q%d" % i, "answer": "5"} for i in range(10)]

LINE_RE = re.compile(
    r"^\[(\d+)/(\d+)\] (\d+)% complete"
    r"(?: \| (\d+) passed, (\d+) failed)?"
    r" \| ([\d.]+) rpm"
    r"(?: \| \$([\d.]+) spent)?"
    r" \| ETA: (\d+)s$")


def progress_lines(run):
    return [line for line in run.stderr.splitlines()
            if line.startswith("[")]


# Spec: "--progress"
# Context: Progress Reporting / CLI flag. Without it, nothing is printed.
def test_no_progress_output_without_the_flag(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert progress_lines(run) == []


# Spec: "print progress updates to stderr"
# Context: Progress Reporting / Rules; stdout stays the JSON summary.
def test_progress_goes_to_stderr_not_stdout(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS,
                       args=["--progress"])
    assert run.returncode == 0, run.stderr
    assert progress_lines(run)
    assert run.summary["total"] == 10          # stdout is still just JSON


# Spec: "[50/100] 50% complete | 42 passed, 8 failed | 58.2 rpm |
#        $2.45 spent | ETA: 52s"
# Context: Progress Reporting / format.
def test_progress_line_format(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost_block()), ROWS,
                       args=["--progress"])
    assert run.returncode == 0, run.stderr
    lines = progress_lines(run)
    assert lines
    for line in lines:
        match = LINE_RE.match(line)
        assert match, line
        done, total, percent = int(match.group(1)), int(match.group(2)), int(match.group(3))
        assert total == 10
        assert 0 <= done <= 10
        assert percent == int(done * 100 / total)
        assert match.group(4) is not None      # passed count present
        assert match.group(7) is not None      # cost present


# Spec: "every 10% of total inputs" - 10 rows means an update per row.
# Context: Progress Reporting / Rules.
def test_update_every_ten_percent_of_inputs(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=1)),
                       ROWS, args=["--progress"])
    assert run.returncode == 0, run.stderr
    lines = progress_lines(run)
    assert len(lines) >= 5
    counts = [int(LINE_RE.match(line).group(1)) for line in lines]
    assert counts == sorted(counts)
    assert counts[-1] == 10


# Spec: "include `passed` / `failed` counts only when evaluation is
#        configured" / "if no evaluation is configured, omit the passed/failed
#        field"
# Context: Progress Reporting / Rules.
def test_passed_failed_omitted_without_evaluation(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None), ROWS,
                       args=["--progress"])
    assert run.returncode == 0, run.stderr
    lines = progress_lines(run)
    assert lines
    for line in lines:
        assert "passed" not in line
        assert LINE_RE.match(line), line


# Spec: "include `$... spent` only when cost tracking is configured" / "if
#        cost tracking is disabled, omit the cost field"
# Context: Progress Reporting / Rules.
def test_cost_field_omitted_without_cost_config(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS, args=["--progress"])
    assert run.returncode == 0, run.stderr
    lines = progress_lines(run)
    assert lines
    for line in lines:
        assert "$" not in line
        assert LINE_RE.match(line), line


# Spec: the passed/failed counts track the evaluation outcome.
def test_passed_and_failed_counts_are_reported(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5" if i % 2 == 0 else "9"}
            for i in range(10)]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, rpm=6000,
                                   rate_limits=limits_block(max_concurrent=1)),
                       rows, args=["--progress"])
    assert run.returncode == 0, run.stderr
    last = progress_lines(run)[-1]
    match = LINE_RE.match(last)
    assert (int(match.group(4)), int(match.group(5))) == (5, 5)


# Spec: the counter reaches the total when the run finishes.
def test_final_update_reports_every_row(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, cost=cost_block()), ROWS,
                       args=["--progress"])
    assert run.returncode == 0, run.stderr
    last = LINE_RE.match(progress_lines(run)[-1])
    assert last.group(1) == "10"
    assert last.group(3) == "100"


# Spec: "[50/100] ... | 58.2 rpm | ... ETA: 52s"
# Context: the rpm and ETA fields are numbers the run can compute.
def test_rpm_and_eta_fields_are_numeric(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS, args=["--progress"])
    assert run.returncode == 0, run.stderr
    for line in progress_lines(run):
        match = LINE_RE.match(line)
        assert float(match.group(6)) >= 0.0
        assert int(match.group(8)) >= 0

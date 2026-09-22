"""Part 5: --resume picks up where a previous run stopped."""
import json

from conftest import make_config, make_multi_config
from mock_api import MockAPI, always, sequence


ROWS = [{"question": "q%d" % i, "answer": "5"} for i in range(6)]


# Spec: "--resume"
# Context: Resume / CLI flag.
def test_resume_flag_is_accepted_without_existing_output(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS[:2],
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert len(run.rows) == 2


# Spec: "if `--resume` is set and the output file already exists, inspect the
#        existing output to determine how many input rows are already
#        complete ... the existing line count gives the number of leading rows
#        to skip"
# Context: Resume / Rules, and "If the output already has 500 lines, skip the
# first 500 input rows and append new results after them."
def test_existing_lines_are_skipped(run_tool):
    with MockAPI(always("#### 5")) as first:
        run = run_tool(make_config(api_url=first.url), ROWS[:3])
    assert run.returncode == 0, run.stderr
    assert first.call_count == 3

    with MockAPI(always("#### 5")) as second:
        run = run_tool(make_config(api_url=second.url), ROWS,
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert second.call_count == 3          # only rows 3, 4, 5


# Spec: "append new rows to the existing output file"
# Context: Resume / Rules.
def test_new_rows_are_appended_to_the_existing_file(run_tool):
    with MockAPI(always("#### 5")) as first:
        run_tool(make_config(api_url=first.url), ROWS[:3])
    with MockAPI(always("#### 5")) as second:
        run = run_tool(make_config(api_url=second.url), ROWS,
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    out = run.rows
    assert len(out) == 6
    assert [r["input"]["question"] for r in out] == ["q%d" % i for i in range(6)]


# Spec: "the summary covers only newly processed rows and includes
#        `resumed_from`"
# Context: Resume / Rules and the example summary
# {"total": 50, "resumed_from": 50, "passed": 42, "failed": 8}.
def test_summary_counts_only_new_rows(run_tool):
    with MockAPI(always("#### 5")) as first:
        run_tool(make_config(api_url=first.url), ROWS[:4])
    with MockAPI(always("#### 5")) as second:
        run = run_tool(make_config(api_url=second.url), ROWS,
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    summary = run.summary
    assert summary["resumed_from"] == 4
    assert summary["total"] == 2
    assert summary["passed"] == 2


# Spec: resuming a finished file does no work at all.
def test_resume_of_a_complete_file_runs_nothing(run_tool):
    with MockAPI(always("#### 5")) as first:
        run_tool(make_config(api_url=first.url), ROWS)
    with MockAPI(always("#### 5")) as second:
        run = run_tool(make_config(api_url=second.url), ROWS,
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert second.call_count == 0
    assert run.summary["total"] == 0
    assert run.summary["resumed_from"] == 6
    assert len(run.rows) == 6


# Spec: without `--resume` the output file is rewritten from scratch.
# Context: "Existing behavior from earlier parts is unchanged unless stated
# here."
def test_without_resume_the_file_is_overwritten(run_tool):
    with MockAPI(always("#### 5")) as first:
        run_tool(make_config(api_url=first.url), ROWS[:3])
    with MockAPI(always("#### 5")) as second:
        run = run_tool(make_config(api_url=second.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert second.call_count == 6
    assert len(run.rows) == 6


# Spec: "when a prior output row represents an incomplete multi-solution or
#        rejection result with fewer passing solutions than `num_solutions`,
#        do not skip that row; reprocess it from scratch"
# Context: Resume / Rules. The first run collects 1 of 2 solutions for the
# single row; the resumed run redoes that row completely.
def test_incomplete_multi_solution_row_is_reprocessed(run_tool):
    rows = [{"question": "q0", "answer": "5"}]
    config = make_config(scheme="rejection", temperature=0.7, n=4,
                         num_solutions=2, max_attempts=3)
    with MockAPI(sequence(["#### 5", "#### 0", "#### 0"])) as first:
        config["task"]["api_url"] = first.url
        run = run_tool(config, rows)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] == 1        # 1 of 2 solutions

    with MockAPI(always("#### 5")) as second:
        config["task"]["api_url"] = second.url
        run = run_tool(config, rows, args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert second.call_count == 2                      # the row ran again
    out = run.rows
    assert len(out) == 1                               # rewritten, not doubled
    assert out[0]["result"]["passed"] == 2
    assert run.summary["resumed_from"] == 0


# Spec: a complete multi-solution row is skipped like any other.
def test_complete_multi_solution_row_is_skipped(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(2)]
    config = make_config(scheme="sample", temperature=0.7, num_solutions=2)
    with MockAPI(always("#### 5")) as first:
        config["task"]["api_url"] = first.url
        run = run_tool(config, rows[:1])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] == 2

    with MockAPI(always("#### 5")) as second:
        config["task"]["api_url"] = second.url
        run = run_tool(config, rows, args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert second.call_count == 2          # only the second row
    assert run.summary["resumed_from"] == 1
    assert len(run.rows) == 2


# Spec: "for multi-task configs, apply resume separately per task output file"
# Context: Resume / Rules.
def test_resume_applies_per_task_output_file(multi):
    inputs = {"gsm8k": [{"question": "q%d" % i, "answer": "5"} for i in range(4)],
              "mmlu": [{"question": "q%d" % i, "answer": "A"} for i in range(4)]}
    with MockAPI(always("#### 5 A")) as first:
        config = make_multi_config(api_url=first.url)
        run = multi.run(config, {"gsm8k": inputs["gsm8k"][:2],
                                 "mmlu": inputs["mmlu"][:3]})
    assert run.returncode == 0, run.stderr

    with MockAPI(always("#### 5 A")) as second:
        config = make_multi_config(api_url=second.url)
        run = multi.run(config, inputs, args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert second.call_count == 2 + 1
    assert len(run.rows("gsm8k")) == 4
    assert len(run.rows("mmlu")) == 4
    assert run.summary["tasks"]["gsm8k"]["resumed_from"] == 2
    assert run.summary["tasks"]["mmlu"]["resumed_from"] == 3


# Spec: "match by input row index" - the appended rows carry the right inputs.
def test_appended_rows_match_their_input_index(run_tool):
    with MockAPI(always("#### 5")) as first:
        run_tool(make_config(api_url=first.url), ROWS[:2])
    with MockAPI(always("#### 5")) as second:
        run = run_tool(make_config(api_url=second.url), ROWS,
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    for index, record in enumerate(run.rows):
        assert record["input"]["question"] == "q%d" % index


# Spec: resume tolerates a blank trailing line in the existing output.
def test_blank_lines_do_not_count_as_completed_rows(run_tool, workdir):
    path = workdir / "results.jsonl"
    done = {"input": ROWS[0], "output": {"solution": "#### 5"},
            "result": {"passed": True, "extracted_answer": "5", "attempts": 1},
            "meta": None}
    path.write_text(json.dumps(done) + "\n\n")
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS[:3],
                       args=["--resume"])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert len(run.rows) == 3

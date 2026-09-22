"""`script` evaluation: rendering, shell execution, exit codes, timeout."""
import json

import pytest

from conftest import make_config, make_multi_config, script_task
from mock_api import MockAPI, always, sequence

import rejector


def script_config(command_template, success_exit_code=0, api_url=None,
                  scheme="greedy", temperature=None, n=None):
    evaluation = {"type": "script", "command_template": command_template,
                  "success_exit_code": success_exit_code}
    return make_config(api_url=api_url, evaluation=evaluation, user="{problem}",
                       system="Write code.", output_field="code",
                       scheme=scheme, temperature=temperature, n=n)


# Spec: "`command_template` may reference row fields and `__response__`"
# Context: `script` evaluation rules.
def test_command_template_expands_row_fields():
    row = {"problem": "p", "code_word": "banana"}
    command = rejector.render_command("echo {code_word}", row, "resp", 0)
    assert command == "echo banana"


def test_command_template_expands_response():
    row = {"problem": "p"}
    command = rejector.render_command("grep -q x <<< '{__response__}'", row,
                                      "xyz", 0)
    assert command == "grep -q x <<< 'xyz'"


# Spec: "if a row field such as `{test_code}` expands to text that itself
# contains `{__response__}`, substitute `__response__` before executing the
# command"
# Context: `script` evaluation rules; the Examples section uses exactly this.
def test_response_inside_an_expanded_row_field_is_substituted():
    row = {"problem": "write good code",
           "test_code": "echo '{__response__}' | grep -q 'good code'"}
    command = rejector.render_command("{test_code}", row, "this is good code", 0)
    assert command == "echo 'this is good code' | grep -q 'good code'"


# Spec: "run the rendered command in a shell"
# Context: `script` evaluation rules.
def test_shell_features_are_available(run_tool):
    with MockAPI(always("ignored")) as api:
        run = run_tool(script_config("echo hello | grep -q hello", api_url=api.url),
                       [{"problem": "p"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


# Spec: "exit code equal to `success_exit_code` means pass; any other exit
# code means fail"
# Context: `script` evaluation rules.
def test_matching_exit_code_passes(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("exit 0", api_url=api.url),
                       [{"problem": "p"}])
    assert run.rows[0]["result"]["passed"] is True


def test_other_exit_code_fails(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("exit 1", api_url=api.url),
                       [{"problem": "p"}])
    assert run.rows[0]["result"]["passed"] is False
    assert run.summary["failed"] == 1


def test_non_zero_success_exit_code_is_honoured(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("exit 3", success_exit_code=3,
                                     api_url=api.url),
                       [{"problem": "p"}])
    assert run.rows[0]["result"]["passed"] is True


def test_zero_exit_fails_when_success_exit_code_is_three(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("exit 0", success_exit_code=3,
                                     api_url=api.url),
                       [{"problem": "p"}])
    assert run.rows[0]["result"]["passed"] is False


# Spec example: row carries `test_code` that greps the response.
# Context: Examples, "Script evaluation example".
@pytest.mark.parametrize("response,passed", [
    ("this is good code", True),
    ("this is bad", False),
])
def test_spec_script_example(run_tool, response, passed):
    row = {"problem": "write good code",
           "test_code": "echo '{__response__}' | grep -q 'good code'"}
    with MockAPI(always(response)) as api:
        run = run_tool(script_config("{test_code}", api_url=api.url), [row])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is passed


def test_python3_command_template_from_the_spec_config(run_tool):
    row = {"problem": "p", "test_code": "import sys; sys.exit(0)"}
    with MockAPI(always("def f(): pass")) as api:
        run = run_tool(script_config('python3 -c "{test_code}"', api_url=api.url),
                       [row])
    assert run.rows[0]["result"]["passed"] is True


# Spec: "capture command stdout and stderr, but do not include them in the
# JSONL output"
# Context: `script` evaluation rules.
def test_command_output_is_not_written_to_the_jsonl(run_tool):
    command = "echo SECRETSTDOUT; echo SECRETSTDERR >&2"
    with MockAPI(always("x")) as api:
        run = run_tool(script_config(command, api_url=api.url),
                       [{"problem": "p"}])
    assert run.returncode == 0, run.stderr
    text = json.dumps(run.rows[0])
    assert "SECRETSTDOUT" not in text
    assert "SECRETSTDERR" not in text


def test_command_output_is_not_printed_to_stdout(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("echo SECRETSTDOUT", api_url=api.url),
                       [{"problem": "p"}])
    assert "SECRETSTDOUT" not in run.stdout
    assert len([l for l in run.stdout.strip().splitlines() if l.strip()]) == 1


# Spec: "command timeout is 10 seconds; timeout is a failed evaluation"
# Context: `script` evaluation rules. This test necessarily waits ~10s.
@pytest.mark.slow
def test_command_that_hangs_times_out_and_fails(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("sleep 30", api_url=api.url),
                       [{"problem": "p"}], timeout=60)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False


# Spec: `script` is a valid evaluation, so it satisfies rejection sampling's
# requirement for an evaluation and drives its accept/reject decision.
# Context: Part 1 rejection rules + Part 2 evaluation additions.
def test_rejection_keeps_the_first_response_that_passes_the_script(run_tool):
    row = {"problem": "p",
           "test_code": "echo '{__response__}' | grep -q GOOD"}
    with MockAPI(sequence(["BAD one", "BAD two", "GOOD three"])) as api:
        run = run_tool(script_config("{test_code}", api_url=api.url,
                                     scheme="rejection", temperature=0.8, n=5),
                       [row])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 3
    assert run.rows[0]["result"]["passed"] is True
    assert run.rows[0]["output"] == {"code": "GOOD three"}


# T28: a script evaluation has no extracted comparison value.
def test_script_rows_report_null_extracted_answer(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("exit 0", api_url=api.url),
                       [{"problem": "p"}])
    assert run.rows[0]["result"]["extracted_answer"] is None


def test_script_rows_have_no_judge_score(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("exit 0", api_url=api.url),
                       [{"problem": "p"}])
    assert "judge_score" not in run.rows[0]["result"]


# Configuration validation for the new type.
def test_script_without_command_template_exits_1(run_tool):
    config = make_config(evaluation={"type": "script"}, user="{problem}")
    run = run_tool(config, [{"problem": "p"}])
    assert run.returncode == 1
    assert run.stderr.strip()


# T31: command placeholders are validated up front, like prompt placeholders.
def test_missing_row_field_for_command_template_exits_1(run_tool):
    with MockAPI(always("x")) as api:
        run = run_tool(script_config("echo {missing_field}", api_url=api.url),
                       [{"problem": "p"}])
    assert run.returncode == 1
    assert "missing_field" in run.stderr


# The script runs once per generated response, not once per row of the file.
def test_script_runs_for_every_row(run_tool, workdir):
    marker = workdir / "hits.txt"
    command = "echo hit >> %s" % marker
    with MockAPI(always("x")) as api:
        run = run_tool(script_config(command, api_url=api.url),
                       [{"problem": "a"}, {"problem": "b"}, {"problem": "c"}])
    assert run.returncode == 0, run.stderr
    assert len(marker.read_text().strip().splitlines()) == 3


# Multi-task: a `script` task lives beside other evaluation types.
def test_script_task_inside_a_multi_task_config(multi):
    tasks = {"code_gen": script_task(command_template="{test_code}")}
    cfg = make_multi_config(tasks=tasks)
    rows = [{"problem": "p", "test_code": "echo '{__response__}' | grep -q ok"}]
    with MockAPI(always("looks ok to me")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"code_gen": rows})
    assert run.returncode == 0, run.stderr
    assert run.rows("code_gen")[0]["result"]["passed"] is True
    assert run.rows("code_gen")[0]["output"] == {"code": "looks ok to me"}


# T41: `success_exit_code` defaults to 0 when the block omits it.
def test_success_exit_code_defaults_to_zero(run_tool):
    config = make_config(api_url=None, user="{problem}",
                         evaluation={"type": "script",
                                     "command_template": "exit 0"},
                         output_field="code")
    with MockAPI(always("x")) as api:
        config["task"]["api_url"] = api.url
        run = run_tool(config, [{"problem": "p"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True

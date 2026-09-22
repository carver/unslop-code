"""`script` evaluation: rendered shell command, exit code, capture, timeout."""

import os

import pytest

import fake_api


def _script(command_template, success_exit_code=0, **kw):
    ev = {"type": "script", "command_template": command_template,
          "success_exit_code": success_exit_code}
    ev.update(kw)
    return {"evaluation": ev, "prompt": {"user": "{problem}", "system": None}}


# ---------------------------------------------------------------------------
# Spec: 'evaluation: type: "script"'
# Context: Evaluation Additions.  `script` is an accepted evaluation type.
# ---------------------------------------------------------------------------
def test_script_is_an_accepted_evaluation_type(run_task):
    with fake_api.FakeAPI(fake_api.always("def f(): pass")) as api:
        res = run_task(api, _script("true"),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "exit code equal to `success_exit_code` means pass"
# Context: script rules.
# ---------------------------------------------------------------------------
def test_exit_code_equal_to_success_exit_code_passes(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("exit 3", success_exit_code=3),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "any other exit code means fail"
# Context: script rules.
# ---------------------------------------------------------------------------
def test_other_exit_code_fails(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("exit 1", success_exit_code=0),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "any other exit code means fail"
# Context: script rules.  A zero exit is a failure when success_exit_code is
# non-zero.
# ---------------------------------------------------------------------------
def test_zero_exit_fails_when_success_exit_code_is_nonzero(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("true", success_exit_code=7),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "`command_template` may reference row fields"
# Context: script rules.
# ---------------------------------------------------------------------------
def test_command_template_references_row_fields(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("exit {code}"),
                       rows=[{"problem": "p", "code": 0},
                             {"problem": "p2", "code": 5}], check=0)
    assert [r["result"]["passed"] for r in res.rows] == [True, False]


# ---------------------------------------------------------------------------
# Spec: "`command_template` may reference row fields and `__response__`"
# Context: script rules.  The generated response text is substituted directly.
# ---------------------------------------------------------------------------
def test_command_template_references_response(run_task):
    with fake_api.FakeAPI(fake_api.always("hello world")) as api:
        res = run_task(api, _script("echo '{__response__}' | grep -q world"),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "`command_template` may reference row fields and `__response__`"
# Context: script rules.  A response that does not satisfy the command fails.
# ---------------------------------------------------------------------------
def test_command_using_response_can_fail(run_task):
    with fake_api.FakeAPI(fake_api.always("goodbye")) as api:
        res = run_task(api, _script("echo '{__response__}' | grep -q world"),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "if a row field such as `{test_code}` expands to text that itself
#        contains `{__response__}`, substitute `__response__` before executing
#        the command"
# Context: script rules.  Two-stage substitution.
# ---------------------------------------------------------------------------
def test_response_is_substituted_inside_an_expanded_row_field(run_task):
    rows = [{"problem": "write good code",
             "test_code": "echo '{__response__}' | grep -q 'good code'"}]
    with fake_api.FakeAPI(fake_api.always("here is good code")) as api:
        res = run_task(api, _script("{test_code}"), rows=rows, check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec (Examples): 'then the rendered shell command uses the generated
#        response text in place of __response__.  A zero exit code passes;
#        non-zero fails.'
# Context: Examples, script evaluation.  The same row with a response that
# does not match.
# ---------------------------------------------------------------------------
def test_script_example_fails_on_a_non_matching_response(run_task):
    rows = [{"problem": "write good code",
             "test_code": "echo '{__response__}' | grep -q 'good code'"}]
    with fake_api.FakeAPI(fake_api.always("here is bad code")) as api:
        res = run_task(api, _script("{test_code}"), rows=rows, check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: 'command_template: "python3 -c \"{test_code}\""'
# Context: script rules.  The documented template shape works.
# ---------------------------------------------------------------------------
def test_python_c_command_template(run_task):
    rows = [{"problem": "p", "test_code": "assert 1 + 1 == 2"},
            {"problem": "p2", "test_code": "assert 1 + 1 == 3"}]
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script('python3 -c "{test_code}"'), rows=rows,
                       check=0)
    assert [r["result"]["passed"] for r in res.rows] == [True, False]


# ---------------------------------------------------------------------------
# Spec: "run the rendered command in a shell"
# Context: script rules.  Shell features (pipes, redirection, globs) work.
# ---------------------------------------------------------------------------
def test_command_runs_in_a_shell(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("echo hi | grep -q hi && true"),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "capture command stdout and stderr, but do not include them in the
#        JSONL output"
# Context: script rules.  Nothing from the command leaks into the row.
# ---------------------------------------------------------------------------
def test_command_output_is_not_in_the_jsonl_row(run_task):
    cmd = "echo SENTINEL_OUT; echo SENTINEL_ERR 1>&2"
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script(cmd), rows=[{"problem": "p"}], check=0)
    text = open(res._output_path).read()
    assert "SENTINEL_OUT" not in text and "SENTINEL_ERR" not in text


# ---------------------------------------------------------------------------
# Spec: "capture command stdout and stderr"
# Context: script rules.  Captured means not forwarded to the tool's own
# stdout (which carries only the summary) or stderr.
# ---------------------------------------------------------------------------
def test_command_output_is_not_forwarded_to_the_tool_streams(run_task):
    cmd = "echo SENTINEL_OUT; echo SENTINEL_ERR 1>&2"
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script(cmd), rows=[{"problem": "p"}], check=0)
    assert "SENTINEL_OUT" not in res.stdout
    assert "SENTINEL_ERR" not in res.stderr


# ---------------------------------------------------------------------------
# Spec: "command timeout is 10 seconds; timeout is a failed evaluation"
# Context: script rules.  A command that never returns fails the row rather
# than hanging the run.
# ---------------------------------------------------------------------------
def test_command_timeout_is_a_failed_evaluation(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("sleep 30"), rows=[{"problem": "p"}],
                       check=0, timeout=60)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "command timeout is 10 seconds"
# Context: script rules.  A command comfortably under the limit still runs to
# completion.
# ---------------------------------------------------------------------------
def test_command_under_the_timeout_completes(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("sleep 0.2; exit 0"),
                       rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "type: script" combined with Part 1 rejection sampling
# Context: script rules + Part 1 "retry until evaluation passes".  The script
# decides which attempt is kept.
# ---------------------------------------------------------------------------
def test_script_evaluation_drives_rejection_sampling(run_task):
    task = _script("echo '{__response__}' | grep -q GOOD")
    task["generation"] = {"scheme": "rejection", "temperature": 0.8, "n": 3}
    with fake_api.FakeAPI(fake_api.sequence(["BAD", "BAD", "GOOD"])) as api:
        res = run_task(api, task, rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["attempts"] == 3
    assert res.rows[0]["result"]["passed"] is True
    assert res.rows[0]["output"] == {"solution": "GOOD"}


# ---------------------------------------------------------------------------
# Spec: 'evaluation: type: "script" ... command_template'
# Context: script rules.  AMBIGUITIES T31 — `command_template` is required.
# ---------------------------------------------------------------------------
def test_script_without_command_template_is_an_error(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, {"evaluation": {"type": "script",
                                            "command_template": None}},
                       rows=[{"question": "q", "answer": "1"}], check=None)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "script" evaluation has no extraction step.
# Context: script rules.  AMBIGUITIES T33 — `extracted_answer` stays null.
# ---------------------------------------------------------------------------
def test_script_rows_have_no_extracted_answer(run_task):
    with fake_api.FakeAPI(fake_api.always("x")) as api:
        res = run_task(api, _script("true"), rows=[{"problem": "p"}], check=0)
    assert res.rows[0]["result"]["extracted_answer"] is None
    assert "judge_score" not in res.rows[0]["result"]


# ---------------------------------------------------------------------------
# Spec: 'code_gen: ... evaluation: type: "script" ... output_field: "code"'
# Context: Configuration example.  A script task inside a multi-task config.
# ---------------------------------------------------------------------------
def test_script_task_in_a_multi_task_config(run_multi):
    tasks = {"code_gen": {
        "prompt": {"system": "Write a Python function.", "user": "{problem}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "script",
                       "command_template": 'python3 -c "{test_code}"',
                       "success_exit_code": 0},
        "output_field": "code",
    }}
    inputs = {"code_gen": [{"problem": "p", "test_code": "assert True"}]}
    with fake_api.FakeAPI(fake_api.always("def f(): pass")) as api:
        res = run_multi(api, tasks=tasks, inputs=inputs, replace_tasks=True,
                        check=0)
    assert res.task_rows("code_gen")[0]["result"]["passed"] is True
    assert res.task_rows("code_gen")[0]["output"] == {"code": "def f(): pass"}

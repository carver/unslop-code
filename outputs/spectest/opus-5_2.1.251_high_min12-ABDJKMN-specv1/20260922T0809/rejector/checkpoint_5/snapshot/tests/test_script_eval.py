"""Spec section: Part 2 / Evaluation Additions (`script` evaluation)."""
from __future__ import annotations

import copy
import json
import time

import pytest

from conftest import SCRIPT_TASK, base_config, multi_config
from mock_server import MockAPI, always, completion, sequence


def _script_config(api_url, command_template, success_exit_code=0, **over):
    """A Part 1 single-task config whose evaluation is a script."""
    evaluation = {"type": "script", "command_template": command_template,
                  "answer_field": None, "extract": None}
    if success_exit_code is not None:
        evaluation["success_exit_code"] = success_exit_code
    return base_config(api_url, evaluation=evaluation, output_field="code",
                       **over)


# ---------------------------------------------------------------------------
# Phrase: "`script` evaluation: type: "script" / command_template /
#          success_exit_code"
# Context: Part 2 / Evaluation Additions.  The spec's config block must load.
# ---------------------------------------------------------------------------
def test_script_evaluation_config_is_accepted(run_tool, write_config,
                                              write_input, workdir):
    with MockAPI(always("print(1)")) as api:
        cfg = write_config(multi_config(api.url,
                                        {"code_gen": copy.deepcopy(SCRIPT_TASK)}))
        data = write_input([{"problem": "print one", "test_code": "pass"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"code_gen={data}"], output=out)
    assert res.returncode == 0, res
    assert res.rows_for("code_gen")[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "exit code equal to `success_exit_code` means pass"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_matching_exit_code_passes(run_tool, write_config, write_input):
    with MockAPI(always("anything")) as api:
        cfg = write_config(_script_config(api.url, "exit 0"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# Context: same phrase - a non-zero `success_exit_code` is honoured literally.
def test_non_zero_success_exit_code_passes(run_tool, write_config, write_input):
    with MockAPI(always("anything")) as api:
        cfg = write_config(_script_config(api.url, "exit 3",
                                          success_exit_code=3))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "any other exit code means fail"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_other_exit_code_fails(run_tool, write_config, write_input):
    with MockAPI(always("anything")) as api:
        cfg = write_config(_script_config(api.url, "exit 1"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False


# Context: same phrase - exit 0 fails when `success_exit_code` is 3.
def test_zero_exit_fails_when_success_code_is_three(run_tool, write_config,
                                                    write_input):
    with MockAPI(always("anything")) as api:
        cfg = write_config(_script_config(api.url, "exit 0",
                                          success_exit_code=3))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False


# Context: same phrase - a failing script still keeps the generated text in
# `output` (AMBIGUITIES T29).
def test_failing_script_keeps_the_generated_output(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("def f(): pass")) as api:
        cfg = write_config(_script_config(api.url, "exit 1"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] == {"code": "def f(): pass"}


# ---------------------------------------------------------------------------
# Phrase: "`command_template` may reference row fields and `__response__`"
# Context: Part 2 / Evaluation Additions.  A row field expands into the shell
# command.
# ---------------------------------------------------------------------------
def test_command_template_expands_row_fields(run_tool, write_config,
                                             write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(api.url, "exit {code}"))
        data = write_input([{"question": "q", "code": 0},
                            {"question": "q", "code": 1}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert [r["result"]["passed"] for r in res.rows] == [True, False]


# Context: same phrase - `{__response__}` in the template itself is the
# generated response text.
def test_command_template_expands_response_directly(run_tool, write_config,
                                                    write_input):
    with MockAPI(always("good code")) as api:
        cfg = write_config(_script_config(
            api.url, "echo '{__response__}' | grep -q 'good code'"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


def test_command_template_response_mismatch_fails(run_tool, write_config,
                                                  write_input):
    with MockAPI(always("bad code")) as api:
        cfg = write_config(_script_config(
            api.url, "echo '{__response__}' | grep -q 'good code'"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Phrase: "if a row field such as `{test_code}` expands to text that itself
#          contains `{__response__}`, substitute `__response__` before
#          executing the command"
# Context: Part 2 / Examples (Script evaluation example).  The row field
# carries the placeholder; substitution must happen in a second pass.
# ---------------------------------------------------------------------------
def test_response_placeholder_nested_in_a_row_field(run_tool, write_config,
                                                    write_input):
    with MockAPI(always("good code")) as api:
        cfg = write_config(_script_config(api.url, "{test_code}"))
        data = write_input([{
            "question": "write good code",
            "problem": "write good code",
            "test_code": "echo '{__response__}' | grep -q 'good code'"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


def test_response_placeholder_nested_in_a_row_field_can_fail(run_tool,
                                                             write_config,
                                                             write_input):
    with MockAPI(always("terrible code")) as api:
        cfg = write_config(_script_config(api.url, "{test_code}"))
        data = write_input([{
            "question": "write good code",
            "problem": "write good code",
            "test_code": "echo '{__response__}' | grep -q 'good code'"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False


# Context: same phrase - substitution is textual, not shell-quoted, so the
# single quotes written by the config author keep working (AMBIGUITIES T28).
def test_response_substitution_is_not_shell_quoted(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("multi word response")) as api:
        cfg = write_config(_script_config(
            api.url, "test \"{__response__}\" = 'multi word response'"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "run the rendered command in a shell"
# Context: Part 2 / Evaluation Additions.  Shell features - pipes, quoting and
# `&&` - must work, which they only do under a shell.
# ---------------------------------------------------------------------------
def test_command_runs_in_a_shell(run_tool, write_config, write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(
            api.url, "echo hello | grep -q hello && true"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "capture command stdout and stderr, but do not include them in the
#          JSONL output"
# Context: Part 2 / Evaluation Additions.  A noisy command must not leak into
# the output row (nor into the tool's own stdout summary line).
# ---------------------------------------------------------------------------
def test_command_output_is_not_in_the_jsonl(run_tool, write_config,
                                            write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(
            api.url, "echo NOISE_ON_STDOUT; echo NOISE_ON_STDERR >&2"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    raw = json.dumps(res.rows[0])
    assert "NOISE_ON_STDOUT" not in raw
    assert "NOISE_ON_STDERR" not in raw


def test_command_output_is_not_on_the_tools_stdout(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(
            api.url, "echo NOISE_ON_STDOUT; echo NOISE_ON_STDERR >&2"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert "NOISE_ON_STDOUT" not in res.stdout
    assert "NOISE_ON_STDERR" not in res.stderr
    res.summary  # the summary is still the only thing on stdout


# ---------------------------------------------------------------------------
# Phrase: "command timeout is 10 seconds; timeout is a failed evaluation"
# Context: Part 2 / Evaluation Additions.  A command that sleeps past the
# limit fails the row rather than hanging or crashing the run.
# ---------------------------------------------------------------------------
def test_command_timeout_is_a_failed_evaluation(run_tool, write_config,
                                                write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(api.url, "sleep 30"))
        data = write_input([{"question": "q"}])
        started = time.monotonic()
        res = run_tool(cfg, data, timeout=60)
        elapsed = time.monotonic() - started
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is False
    assert elapsed < 25, "the 10s command timeout was not enforced"


# Context: same phrase - a command just under the limit still runs to
# completion.
def test_command_under_the_timeout_completes(run_tool, write_config,
                                             write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(api.url, "sleep 0.2; exit 0"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data, timeout=60)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "`script` evaluation" combined with Part 1's
#         "`rejection`: ... keep the first passing response"
# Context: Part 2 / Evaluation Additions.  Script verdicts drive rejection
# sampling exactly like `exact_match` verdicts do.
# ---------------------------------------------------------------------------
def test_script_evaluation_drives_rejection_sampling(run_tool, write_config,
                                                     write_input):
    with MockAPI(sequence(["bad code", "bad code", "good code"])) as api:
        cfg = write_config(_script_config(
            api.url, "echo '{__response__}' | grep -q 'good code'",
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    row = res.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"code": "good code"}


def test_script_rejection_exhaustion_outputs_null(run_tool, write_config,
                                                  write_input):
    with MockAPI(always("bad code")) as api:
        cfg = write_config(_script_config(
            api.url, "echo '{__response__}' | grep -q 'good code'",
            generation={"scheme": "rejection", "temperature": 0.8, "n": 2}))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] is None
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Phrase: "`result.extracted_answer` is ..." (Part 1) with `type: "script"`
# Context: Part 2 / Evaluation Additions.  A script evaluation extracts
# nothing from the response (AMBIGUITIES T27).
# ---------------------------------------------------------------------------
def test_script_evaluation_extracted_answer_is_null(run_tool, write_config,
                                                    write_input):
    with MockAPI(always("some code")) as api:
        cfg = write_config(_script_config(api.url, "exit 0"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] is None


# Context: a script evaluation adds no `judge_score` key (AMBIGUITIES T26).
def test_script_rows_have_no_judge_score(run_tool, write_config, write_input):
    with MockAPI(always("some code")) as api:
        cfg = write_config(_script_config(api.url, "exit 0"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert "judge_score" not in res.rows[0]["result"]


# ---------------------------------------------------------------------------
# Phrase: "`command_template`" (required for `type: "script"`)
# Context: Part 2 / Evaluation Additions.  A script evaluation without a
# command is a configuration error.
# ---------------------------------------------------------------------------
def test_script_without_command_template_exits_1(run_tool, write_config,
                                                 write_input):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        evaluation={"type": "script", "answer_field": None,
                    "extract": None, "success_exit_code": 0}))
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - `success_exit_code` defaults to 0 when omitted.
def test_success_exit_code_defaults_to_zero(run_tool, write_config,
                                            write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(api.url, "exit 0",
                                          success_exit_code=None))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "`command_template` may reference row fields" + Part 1's
#         "If a placeholder references a missing field, exit with code 1"
# Context: Part 2 / Evaluation Additions (AMBIGUITIES T39).
# ---------------------------------------------------------------------------
def test_missing_command_template_field_exits_1(run_tool, write_config,
                                                write_input):
    cfg = write_config(_script_config("http://127.0.0.1:1", "{test_code}"))
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert "test_code" in res.stderr


# Context: same phrase - `__response__` is supplied at runtime and is never a
# required row field.
def test_response_placeholder_is_not_a_required_row_field(run_tool,
                                                          write_config,
                                                          write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(
            api.url, "echo '{__response__}' | grep -q x"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "script evaluation" - no extra API traffic
# Context: Part 2.  Unlike `llm_judge`, a script evaluation makes no API call.
# ---------------------------------------------------------------------------
def test_script_evaluation_makes_no_extra_api_call(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("x")) as api:
        cfg = write_config(_script_config(api.url, "exit 0"))
        data = write_input([{"question": "q"}, {"question": "q2"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 2
    assert res.summary["total_api_calls"] == 2

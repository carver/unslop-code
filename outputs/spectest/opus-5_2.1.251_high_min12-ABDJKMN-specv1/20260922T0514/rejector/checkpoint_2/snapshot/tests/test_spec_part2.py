"""Tests derived phrase-by-phrase from the Part 2 spec.

Part 2 adds multi-task config files (`defaults` + `tasks`), the `letter` and
`first_number` extract methods, and the `script` and `llm_judge` evaluation
types.  Each section comment quotes the spec phrase under test plus the
minimal context needed to read it.
"""
import copy
import json
import subprocess
import sys

import pytest
import yaml

from conftest import (REJECTOR, completion, judge_split, make_config,
                      make_multi_config)

MATH_ROWS = [{"question": "What is 2 + 3?", "answer": "5"}]
MMLU_ROWS = [{"question": "What is the capital of France?", "a": "London",
              "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B"}]
REVIEW_ROWS = [{"prompt_text": "Describe the sea.", "criteria": "clarity"}]
CODE_ROWS = [{"problem": "write good code",
              "test_code": "echo '{__response__}' | grep -q 'good code'"}]

# The four task blocks from the spec's canonical multi-task config.
GSM8K = {
    "prompt": {
        "system": "Solve the math problem step by step. Put your final answer after ####.",
        "user": "{question}",
    },
    "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5},
    "evaluation": {"type": "exact_match", "answer_field": "answer",
                   "extract": "last_number"},
    "output_field": "solution",
}
GSM8K_GREEDY = dict(GSM8K, generation={"scheme": "greedy"})
MMLU = {
    "prompt": {
        "system": "Answer the multiple choice question with a single letter.",
        "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "exact_match", "answer_field": "answer",
                   "extract": "letter"},
    "output_field": "choice",
}
CODE_GEN = {
    "prompt": {
        "system": "Write a Python function to solve the problem.",
        "user": "{problem}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {"type": "script", "command_template": "{test_code}",
                   "success_exit_code": 0},
    "output_field": "code",
}
REVIEW = {
    "prompt": {
        "system": "You are a writing assistant. Write a response to the given prompt.",
        "user": "{prompt_text}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only a single "
                      "integer from 1 to 10.",
            "user": "Rate the quality of this response.\n\nOriginal prompt: "
                    "{prompt_text}\n\nResponse:\n{__response__}\n\n"
                    "Criteria: {criteria}\n\nScore:",
        },
        "threshold": 7,
        "extract": "first_number",
    },
    "output_field": "response",
}


def task(block, **over):
    """A deep copy of one of the canonical task blocks, with overrides."""
    out = copy.deepcopy(block)
    for key, value in over.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def rows_n(n, **extra):
    base = dict(MATH_ROWS[0])
    base.update(extra)
    return [dict(base, question="q%d" % i) for i in range(n)]


# ---------------------------------------------------------------------------
# Configuration
# "Multi-task configs use `defaults` plus a `tasks` mapping"
# ---------------------------------------------------------------------------

def test_multi_task_config_runs_every_task(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url,
                            {"gsm8k": task(GSM8K_GREEDY), "second": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "second": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert len(r.rows("gsm8k")) == 1
    assert len(r.rows("second")) == 1


def test_each_task_uses_its_own_prompt(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {
        "alpha": task(GSM8K_GREEDY, prompt={"system": "SYS-A", "user": "{question}"}),
        "beta": task(GSM8K_GREEDY, prompt={"system": "SYS-B", "user": "{question}"}),
    })
    r = run_multi(cfg, {"alpha": MATH_ROWS, "beta": MATH_ROWS})
    assert r.code == 0, r.stderr
    systems = {b["messages"][0]["content"] for b in mock.bodies}
    assert systems == {"SYS-A", "SYS-B"}


def test_each_task_uses_its_own_output_field(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {
        "alpha": task(GSM8K_GREEDY, output_field="solution"),
        "beta": task(GSM8K_GREEDY, output_field="answer_text"),
    })
    r = run_multi(cfg, {"alpha": MATH_ROWS, "beta": MATH_ROWS})
    assert list(r.rows("alpha")[0]["output"]) == ["solution"]
    assert list(r.rows("beta")[0]["output"]) == ["answer_text"]


def test_each_task_uses_its_own_generation_settings(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {
        "greedy_task": task(GSM8K_GREEDY),
        "sample_task": task(GSM8K_GREEDY,
                            generation={"scheme": "sample", "temperature": 0.9}),
    })
    r = run_multi(cfg, {"greedy_task": MATH_ROWS, "sample_task": MATH_ROWS})
    assert r.code == 0, r.stderr
    temps = sorted(b["temperature"] for b in mock.bodies)
    assert temps == [0.0, 0.9]


def test_each_task_uses_its_own_evaluation(run_multi, api):
    mock = api(lambda body, i: (200, completion("The answer is B) Paris")))
    cfg = make_multi_config(mock.url, {
        "gsm8k": task(GSM8K_GREEDY),          # last_number / exact_match -> fails
        "mmlu": task(MMLU),                   # letter / exact_match -> passes
    })
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "mmlu": MMLU_ROWS})
    assert r.rows("gsm8k")[0]["result"]["passed"] is False
    assert r.rows("mmlu")[0]["result"]["passed"] is True


# "defaults provides shared values; each task overrides defaults"
def test_defaults_supply_shared_values(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert echo_api.bodies[0]["model"] == "gpt-4"


def test_task_overrides_a_defaults_scalar(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {
        "plain": task(GSM8K_GREEDY),
        "special": task(GSM8K_GREEDY, model="gpt-4o-mini"),
    })
    r = run_multi(cfg, {"plain": MATH_ROWS, "special": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert sorted(b["model"] for b in mock.bodies) == ["gpt-4", "gpt-4o-mini"]


# "nested sections such as prompt, generation, and evaluation are merged per
#  task using the Part 1 structure"
def test_nested_generation_section_is_merged_not_replaced(run_multi, echo_api):
    cfg = make_multi_config(
        echo_api.url,
        {"gsm8k": task(GSM8K_GREEDY, generation={"scheme": "greedy"})},
        defaults={"generation": {"max_tokens": 321}},
    )
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    body = echo_api.bodies[0]
    assert body["max_tokens"] == 321      # from defaults
    assert body["temperature"] == 0.0     # from the task's scheme


def test_task_generation_key_wins_over_defaults(run_multi, echo_api):
    cfg = make_multi_config(
        echo_api.url,
        {"gsm8k": task(GSM8K_GREEDY, generation={"scheme": "greedy", "max_tokens": 64})},
        defaults={"generation": {"max_tokens": 321}},
    )
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert echo_api.bodies[0]["max_tokens"] == 64


def test_nested_prompt_section_is_merged(run_multi, echo_api):
    cfg = make_multi_config(
        echo_api.url,
        {"gsm8k": task(GSM8K_GREEDY, prompt={"user": "{question}"})},
        defaults={"prompt": {"system": "SHARED SYSTEM"}},
    )
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert echo_api.bodies[0]["messages"][0]["content"] == "SHARED SYSTEM"


def test_nested_evaluation_section_is_merged(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(
        mock.url,
        {"gsm8k": task(GSM8K_GREEDY, evaluation={"extract": "last_number"})},
        defaults={"evaluation": {"type": "exact_match", "answer_field": "answer"}},
    )
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr
    assert r.rows("gsm8k")[0]["result"]["passed"] is True


# "required Part 1 fields must still come from either defaults or the task"
def test_required_field_may_come_from_the_task_block(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url,
                            {"gsm8k": task(GSM8K_GREEDY, model="gpt-4")},
                            defaults={"model": None})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 0, r.stderr


@pytest.mark.parametrize("missing", ["api_url", "model", "output_field"])
def test_required_field_missing_from_both_exits_one(run_multi, echo_api, missing):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    cfg["defaults"].pop(missing, None)
    cfg["tasks"]["gsm8k"].pop(missing, None)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 1
    assert r.stderr.strip()


def test_missing_prompt_for_one_task_exits_one(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {
        "ok": task(GSM8K_GREEDY),
        "broken": task(GSM8K_GREEDY, prompt=None),
    })
    r = run_multi(cfg, {"ok": MATH_ROWS, "broken": MATH_ROWS})
    assert r.code == 1
    assert r.stderr.strip()


def test_invalid_task_config_names_the_task_on_stderr(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {
        "gsm8k": task(GSM8K_GREEDY),
        "bad_one": task(GSM8K_GREEDY, generation={"scheme": "nonsense"}),
    })
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "bad_one": MATH_ROWS})
    assert r.code == 1
    assert "bad_one" in r.stderr


# "if the config still uses a top-level task key, treat it as the Part 1
#  single-task format; the task name is task.name"
def test_top_level_task_key_is_part_one_format(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 1
    assert "tasks" not in r.summary


def test_single_task_config_keeps_single_output_file(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert r.out_path.is_file()


def test_config_with_both_task_and_tasks_prefers_single_task_format(run_cli, echo_api):
    cfg = make_config(echo_api.url)
    cfg["tasks"] = {"other": task(GSM8K_GREEDY)}
    r = run_cli(cfg, MATH_ROWS)
    assert r.code == 0, r.stderr
    assert "tasks" not in r.summary


def test_config_with_neither_task_nor_tasks_exits_one(run_cli, echo_api):
    r = run_cli({"defaults": {"model": "gpt-4"}}, MATH_ROWS)
    assert r.code == 1
    assert r.stderr.strip()


def test_empty_tasks_mapping_exits_one(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {})
    r = run_multi(cfg, {}, mode="none")
    assert r.code == 1


# ---------------------------------------------------------------------------
# Evaluation Additions — extract methods
# "letter: extract the first uppercase answer choice A through D; accept forms
#  such as A, (A), A), or Answer: A"
# ---------------------------------------------------------------------------

def letter_cfg(url):
    return make_config(url, evaluation={"type": "exact_match",
                                        "answer_field": "answer",
                                        "extract": "letter"})


@pytest.mark.parametrize("text,expected", [
    ("B", "B"),
    ("(B)", "B"),
    ("B)", "B"),
    ("Answer: B", "B"),
])
def test_letter_accepts_the_documented_forms(run_cli, api, text, expected):
    mock = api(lambda body, i: (200, completion(text)))
    r = run_cli(letter_cfg(mock.url), [{"question": "q", "answer": "B"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["extracted_answer"] == expected
    assert r.rows[0]["result"]["passed"] is True


@pytest.mark.parametrize("letter", ["A", "B", "C", "D"])
def test_letter_covers_a_through_d(run_cli, api, letter):
    mock = api(lambda body, i: (200, completion("Answer: %s" % letter)))
    r = run_cli(letter_cfg(mock.url), [{"question": "q", "answer": letter}])
    assert r.rows[0]["result"]["extracted_answer"] == letter


def test_letter_takes_the_first_choice_in_the_response(run_cli, api):
    mock = api(lambda body, i: (200, completion("C then D")))
    r = run_cli(letter_cfg(mock.url), [{"question": "q", "answer": "C"}])
    assert r.rows[0]["result"]["extracted_answer"] == "C"


def test_letter_ignores_lowercase_choices(run_cli, api):
    mock = api(lambda body, i: (200, completion("the answer is b")))
    r = run_cli(letter_cfg(mock.url), [{"question": "q", "answer": "B"}])
    assert r.rows[0]["result"]["passed"] is False


def test_letter_with_no_choice_present(run_cli, api):
    mock = api(lambda body, i: (200, completion("no choice here")))
    r = run_cli(letter_cfg(mock.url), [{"question": "q", "answer": "B"}])
    assert r.rows[0]["result"]["extracted_answer"] is None
    assert r.rows[0]["result"]["passed"] is False


# T18: only a standalone A-D counts, so a capitalised word is not a choice.
def test_letter_skips_letters_inside_words(run_cli, api):
    mock = api(lambda body, i: (200, completion("Berlin is wrong; the answer is B")))
    r = run_cli(letter_cfg(mock.url), [{"question": "q", "answer": "B"}])
    assert r.rows[0]["result"]["extracted_answer"] == "B"


# "first_number: extract the first integer or decimal in the response"
def number_cfg(url):
    return make_config(url, evaluation={"type": "exact_match",
                                        "answer_field": "answer",
                                        "extract": "first_number"})


def test_first_number_takes_the_first_integer(run_cli, api):
    mock = api(lambda body, i: (200, completion("7 then 9 then 11")))
    r = run_cli(number_cfg(mock.url), [{"question": "q", "answer": "7"}])
    assert r.rows[0]["result"]["extracted_answer"] == "7"
    assert r.rows[0]["result"]["passed"] is True


def test_first_number_takes_a_decimal(run_cli, api):
    mock = api(lambda body, i: (200, completion("score 3.5 out of 10")))
    r = run_cli(number_cfg(mock.url), [{"question": "q", "answer": "3.5"}])
    assert r.rows[0]["result"]["extracted_answer"] == "3.5"


def test_first_number_with_no_number(run_cli, api):
    mock = api(lambda body, i: (200, completion("no digits at all")))
    r = run_cli(number_cfg(mock.url), [{"question": "q", "answer": "3"}])
    assert r.rows[0]["result"]["extracted_answer"] is None
    assert r.rows[0]["result"]["passed"] is False


def test_first_number_differs_from_last_number(run_cli, api):
    mock = api(lambda body, i: (200, completion("first 2 last 8")))
    first = run_cli(number_cfg(mock.url), [{"question": "q", "answer": "2"}])
    last = run_cli(make_config(mock.url), [{"question": "q", "answer": "8"}])
    assert first.rows[0]["result"]["extracted_answer"] == "2"
    assert last.rows[0]["result"]["extracted_answer"] == "8"


def test_new_extract_methods_are_accepted_in_multi_task_configs(run_multi, api):
    mock = api(lambda body, i: (200, completion("The answer is B) Paris")))
    cfg = make_multi_config(mock.url, {"mmlu": task(MMLU)})
    r = run_multi(cfg, {"mmlu": MMLU_ROWS})
    assert r.code == 0, r.stderr
    assert r.rows("mmlu")[0]["result"]["extracted_answer"] == "B"


# ---------------------------------------------------------------------------
# `script` evaluation
# "command_template may reference row fields and __response__"
# ---------------------------------------------------------------------------

def script_cfg(url, **ev):
    evaluation = {"type": "script", "command_template": "true", "success_exit_code": 0}
    evaluation.update(ev)
    return make_config(url, evaluation=evaluation,
                       generation={"scheme": "greedy", "max_tokens": 256})


def test_script_command_template_uses_a_row_field(run_cli, api):
    mock = api(lambda body, i: (200, completion("ignored")))
    cfg = script_cfg(mock.url, command_template="test '{expect}' = 'yes'")
    r = run_cli(cfg, [{"question": "q", "expect": "yes"}, {"question": "q", "expect": "no"}])
    assert r.code == 0, r.stderr
    assert [row["result"]["passed"] for row in r.rows] == [True, False]


def test_script_command_template_uses_the_response(run_cli, api):
    mock = api(lambda body, i: (200, completion("good code")))
    cfg = script_cfg(mock.url, command_template="test '{__response__}' = 'good code'")
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# "if a row field such as {test_code} expands to text that itself contains
#  {__response__}, substitute __response__ before executing the command"
def test_script_substitutes_response_nested_inside_a_row_field(run_cli, api):
    mock = api(lambda body, i: (200, completion("this is good code")))
    cfg = script_cfg(mock.url, command_template="{test_code}")
    rows = [{"question": "q", "test_code": "echo '{__response__}' | grep -q 'good code'"}]
    r = run_cli(cfg, rows)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


def test_script_nested_response_can_fail(run_cli, api):
    mock = api(lambda body, i: (200, completion("this is bad")))
    cfg = script_cfg(mock.url, command_template="{test_code}")
    rows = [{"question": "q", "test_code": "echo '{__response__}' | grep -q 'good code'"}]
    r = run_cli(cfg, rows)
    assert r.rows[0]["result"]["passed"] is False


# "run the rendered command in a shell"
def test_script_command_runs_in_a_shell(run_cli, api):
    mock = api(lambda body, i: (200, completion("hello")))
    # Pipes, quoting and exit-status chaining only work through a shell.
    cfg = script_cfg(mock.url, command_template="echo '{__response__}' | grep -q hello && true")
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


# "exit code equal to success_exit_code means pass; any other exit code means
#  fail"
def test_script_zero_exit_passes(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    r = run_cli(script_cfg(mock.url, command_template="exit 0"), [{"question": "q"}])
    assert r.rows[0]["result"]["passed"] is True


@pytest.mark.parametrize("code", [1, 2, 7])
def test_script_other_exit_codes_fail(run_cli, api, code):
    mock = api(lambda body, i: (200, completion("x")))
    r = run_cli(script_cfg(mock.url, command_template="exit %d" % code),
                [{"question": "q"}])
    assert r.rows[0]["result"]["passed"] is False


def test_script_success_exit_code_can_be_non_zero(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    cfg = script_cfg(mock.url, command_template="exit 3", success_exit_code=3)
    r = run_cli(cfg, [{"question": "q"}])
    assert r.rows[0]["result"]["passed"] is True


def test_script_zero_exit_fails_when_success_exit_code_is_three(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    cfg = script_cfg(mock.url, command_template="exit 0", success_exit_code=3)
    r = run_cli(cfg, [{"question": "q"}])
    assert r.rows[0]["result"]["passed"] is False


# "capture command stdout and stderr, but do not include them in the JSONL
#  output"
def test_script_output_is_not_written_to_the_jsonl(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    cfg = script_cfg(
        mock.url,
        command_template="echo MARKER_STDOUT_9182; echo MARKER_STDERR_9182 >&2")
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    raw = r.out_path.read_text()
    assert "MARKER_STDOUT_9182" not in raw
    assert "MARKER_STDERR_9182" not in raw


def test_script_output_is_not_leaked_to_the_cli_stdout(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    cfg = script_cfg(mock.url, command_template="echo MARKER_STDOUT_9182")
    r = run_cli(cfg, [{"question": "q"}])
    assert "MARKER_STDOUT_9182" not in r.stdout


# "command timeout is 10 seconds; timeout is a failed evaluation"
def test_script_timeout_is_a_failed_evaluation(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    cfg = script_cfg(mock.url, command_template="sleep 45")
    r = run_cli(cfg, [{"question": "q"}], timeout=40)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False


def test_script_timeout_keeps_the_generated_output(run_cli, api):
    mock = api(lambda body, i: (200, completion("kept")))
    cfg = script_cfg(mock.url, command_template="sleep 45")
    r = run_cli(cfg, [{"question": "q"}], timeout=40)
    assert r.rows[0]["output"] == {"solution": "kept"}


def test_script_evaluation_requires_command_template(run_cli, echo_api):
    cfg = make_config(echo_api.url, evaluation={"type": "script",
                                                "success_exit_code": 0})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 1
    assert r.stderr.strip()


# T21: success_exit_code defaults to 0 when omitted.
def test_script_success_exit_code_defaults_to_zero(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    cfg = make_config(mock.url, evaluation={"type": "script",
                                            "command_template": "exit 0"})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is True


def test_script_does_not_require_answer_field(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    r = run_cli(script_cfg(mock.url, command_template="true"), [{"question": "q"}])
    assert r.code == 0, r.stderr


def test_script_row_missing_a_command_template_field_exits_one(run_cli, echo_api):
    cfg = script_cfg(echo_api.url, command_template="test '{missing_field}' = 'x'")
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 1
    assert "missing_field" in r.stderr


# script evaluation drives rejection sampling like any other evaluation.
def test_script_evaluation_drives_rejection(run_cli, api):
    def responder(body, i):
        return 200, completion("bad" if i < 2 else "good")
    mock = api(responder)
    cfg = make_config(
        mock.url,
        generation={"scheme": "rejection", "temperature": 0.7, "n": 5, "max_tokens": 256},
        evaluation={"type": "script",
                    "command_template": "test '{__response__}' = 'good'",
                    "success_exit_code": 0})
    r = run_cli(cfg, [{"question": "q"}])
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 3
    assert r.rows[0]["result"]["passed"] is True


def test_script_evaluation_in_a_multi_task_config(run_multi, api):
    mock = api(lambda body, i: (200, completion("this is good code")))
    cfg = make_multi_config(mock.url, {"code_gen": task(CODE_GEN)})
    r = run_multi(cfg, {"code_gen": CODE_ROWS})
    assert r.code == 0, r.stderr
    assert r.rows("code_gen")[0]["result"]["passed"] is True


# T20: the configured extract still fills result.extracted_answer for script
# rows (default "full").
def test_script_row_reports_an_extracted_answer(run_cli, api):
    mock = api(lambda body, i: (200, completion("hello")))
    r = run_cli(script_cfg(mock.url, command_template="true"), [{"question": "q"}])
    assert r.rows[0]["result"]["extracted_answer"] == "hello"


# T25: no judge ran, so no judge_score key is emitted.
def test_script_row_has_no_judge_score(run_cli, api):
    mock = api(lambda body, i: (200, completion("hello")))
    r = run_cli(script_cfg(mock.url, command_template="true"), [{"question": "q"}])
    assert "judge_score" not in r.rows[0]["result"]


def test_script_makes_no_extra_api_calls(run_cli, api):
    mock = api(lambda body, i: (200, completion("x")))
    r = run_cli(script_cfg(mock.url, command_template="true"),
                [{"question": "q"}, {"question": "q2"}])
    assert r.summary["total_api_calls"] == 2


# ---------------------------------------------------------------------------
# `llm_judge` evaluation
# "judge_prompt uses the same template rules as normal prompts"
# "__response__ is the generated response text"
# ---------------------------------------------------------------------------

JUDGE_PROMPT = {
    "system": "You are a quality evaluator. Respond with only a single integer "
              "from 1 to 10.",
    "user": "Rate this response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:",
}
JUDGE_ROWS = [{"question": "Describe the sea.", "criteria": "clarity"}]


def judge_cfg(url, **ev):
    evaluation = {"type": "llm_judge", "judge_prompt": copy.deepcopy(JUDGE_PROMPT),
                  "threshold": 7, "extract": "first_number"}
    evaluation.update(ev)
    return make_config(url, evaluation=evaluation)


def judge_bodies(mock):
    return [b for b in mock.bodies if "evaluator" in b["messages"][0]["content"]]


def gen_bodies(mock):
    return [b for b in mock.bodies if "evaluator" not in b["messages"][0]["content"]]


def test_judge_prompt_system_and_user_are_sent(run_cli, api):
    mock = judge_split(api, "a fine answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    judge = judge_bodies(mock)[0]
    assert judge["messages"][0]["role"] == "system"
    assert judge["messages"][1]["role"] == "user"


def test_judge_prompt_placeholders_come_from_the_row(run_cli, api):
    mock = judge_split(api, "a fine answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert "Criteria: clarity" in judge_bodies(mock)[0]["messages"][1]["content"]


def test_judge_prompt_receives_the_generated_response(run_cli, api):
    mock = judge_split(api, "SEA-ANSWER-TEXT", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert "SEA-ANSWER-TEXT" in judge_bodies(mock)[0]["messages"][1]["content"]
    assert "{__response__}" not in judge_bodies(mock)[0]["messages"][1]["content"]


def test_judge_row_missing_a_judge_prompt_field_exits_one(run_cli, echo_api):
    cfg = judge_cfg(echo_api.url)
    r = run_cli(cfg, [{"question": "q"}])     # no "criteria"
    assert r.code == 1
    assert "criteria" in r.stderr


# "the judge request is a separate API call through the same server"
def test_judge_is_a_separate_api_call(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert len(gen_bodies(mock)) == 1
    assert len(judge_bodies(mock)) == 1
    assert mock.call_count == 2


def test_judge_request_uses_the_same_chat_completions_endpoint(run_cli, api):
    mock = judge_split(api, "answer", "8")
    run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    with mock.lock:
        paths = {r["path"] for r in mock.requests}
    assert paths == {"/v1/chat/completions"}


# "if evaluation.model is omitted, use the task's model"
def test_judge_defaults_to_the_task_model(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert judge_bodies(mock)[0]["model"] == "gpt-4"


def test_judge_uses_evaluation_model_when_present(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url, model="judge-model-1"), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert judge_bodies(mock)[0]["model"] == "judge-model-1"
    assert gen_bodies(mock)[0]["model"] == "gpt-4"


# "score >= threshold passes"
@pytest.mark.parametrize("score,passed", [("6", False), ("7", True), ("8", True),
                                          ("10", True), ("1", False)])
def test_judge_threshold_comparison(run_cli, api, score, passed):
    mock = judge_split(api, "answer", score)
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is passed


def test_judge_score_equal_to_threshold_passes(run_cli, api):
    mock = judge_split(api, "answer", "The score is 7 out of 10")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.rows[0]["result"]["judge_score"] == 7


# "result includes judge_score, and result.extracted_answer is the text extract
#  took from the judge's reply (\"8\" for a score of 8)"
def test_result_includes_judge_score_and_extracted_answer(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    result = r.rows[0]["result"]
    assert result["judge_score"] == 8
    assert result["extracted_answer"] == "8"


def test_extracted_answer_comes_from_the_judge_not_the_response(run_cli, api):
    mock = judge_split(api, "the response mentions 42", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.rows[0]["result"]["extracted_answer"] == "8"


def test_judge_output_field_still_holds_the_generated_response(run_cli, api):
    mock = judge_split(api, "the generated text", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.rows[0]["output"] == {"solution": "the generated text"}


# T23: a non-numeric judge reply yields no score and a failed row.
def test_judge_reply_without_a_number_fails_the_row(run_cli, api):
    mock = judge_split(api, "answer", "excellent work")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False
    assert r.rows[0]["result"]["judge_score"] is None
    assert r.rows[0]["result"]["extracted_answer"] is None


# "meta includes a judge_meta object with the judge request's token usage,
#  latency, model, and finish reason"
def test_meta_includes_judge_meta(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    judge_meta = r.rows[0]["meta"]["judge_meta"]
    assert set(judge_meta) == {"model", "prompt_tokens", "completion_tokens",
                               "total_tokens", "latency_ms", "finish_reason"}


def test_judge_meta_records_token_usage_and_finish_reason(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    judge_meta = r.rows[0]["meta"]["judge_meta"]
    assert judge_meta["prompt_tokens"] == 30
    assert judge_meta["completion_tokens"] == 10
    assert judge_meta["total_tokens"] == 40
    assert judge_meta["finish_reason"] == "stop"


def test_judge_meta_records_the_judge_model(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url, model="judge-model-2"), JUDGE_ROWS)
    assert r.rows[0]["meta"]["judge_meta"]["model"] == "judge-model-2"


def test_judge_meta_records_latency(run_cli, api):
    mock = judge_split(api, "answer", "8", delay=0.25)
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.rows[0]["meta"]["judge_meta"]["latency_ms"] >= 200


def test_generation_meta_is_still_present_alongside_judge_meta(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    meta = r.rows[0]["meta"]
    assert meta["finish_reason"] == "stop"
    assert meta["prompt_tokens"] == 30


# "judge calls count toward throughput, total_api_calls, and per-task API call
#  totals"
def test_judge_calls_count_toward_total_api_calls(run_cli, api):
    mock = judge_split(api, "answer", "8")
    rows = [dict(JUDGE_ROWS[0], question="q%d" % i) for i in range(4)]
    r = run_cli(judge_cfg(mock.url), rows)
    assert r.summary["total_api_calls"] == 8


def test_judge_calls_count_toward_per_task_totals(run_multi, api):
    mock = judge_split(api, "answer", "8")
    cfg = make_multi_config(mock.url, {"review": task(REVIEW)})
    rows = [dict(REVIEW_ROWS[0], prompt_text="p%d" % i) for i in range(3)]
    r = run_multi(cfg, {"review": rows})
    assert r.code == 0, r.stderr
    assert r.summary["tasks"]["review"]["total_api_calls"] == 6


def test_judge_calls_count_toward_throughput(run_cli, api):
    mock = judge_split(api, "answer", "8")
    rows = [dict(JUDGE_ROWS[0], question="q%d" % i) for i in range(4)]
    r = run_cli(judge_cfg(mock.url), rows)
    s = r.summary
    assert s["total_api_calls"] == 8
    # elapsed_seconds is rounded to 0.1, so bound the formula by that window.
    lo = s["total_api_calls"] / (s["elapsed_seconds"] + 0.05) * 60
    hi = s["total_api_calls"] / max(s["elapsed_seconds"] - 0.05, 1e-6) * 60
    assert lo - 1 <= s["throughput_rpm"] <= hi + 1


# T24: judge token usage is included in the summary token totals.
def test_judge_tokens_count_in_summary_token_totals(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.summary["total_prompt_tokens"] == 60
    assert r.summary["total_completion_tokens"] == 20


# llm_judge drives rejection sampling: one judge call per attempt.
def test_llm_judge_drives_rejection_sampling(run_cli, api):
    state = {"gen": 0}

    def responder(body, i):
        system = body["messages"][0]["content"]
        if "evaluator" in system:
            # First two generations score 3, the third scores 9.
            return 200, completion("3" if state["gen"] <= 2 else "9")
        state["gen"] += 1
        return 200, completion("draft %d" % state["gen"])

    mock = api(responder)
    cfg = make_config(
        mock.url,
        generation={"scheme": "rejection", "temperature": 0.7, "n": 5, "max_tokens": 256},
        evaluation={"type": "llm_judge", "judge_prompt": copy.deepcopy(JUDGE_PROMPT),
                    "threshold": 7, "extract": "first_number"})
    r = run_cli(cfg, JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["attempts"] == 3
    assert r.rows[0]["result"]["passed"] is True


# T26: with multiple attempts each metadata entry carries its own judge_meta.
def test_rejection_meta_list_entries_carry_judge_meta(run_cli, api):
    state = {"gen": 0}

    def responder(body, i):
        system = body["messages"][0]["content"]
        if "evaluator" in system:
            return 200, completion("3" if state["gen"] <= 1 else "9")
        state["gen"] += 1
        return 200, completion("draft %d" % state["gen"])

    mock = api(responder)
    cfg = make_config(
        mock.url,
        generation={"scheme": "rejection", "temperature": 0.7, "n": 3, "max_tokens": 256},
        evaluation={"type": "llm_judge", "judge_prompt": copy.deepcopy(JUDGE_PROMPT),
                    "threshold": 7, "extract": "first_number"})
    r = run_cli(cfg, JUDGE_ROWS)
    meta = r.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 2
    assert all("judge_meta" in entry for entry in meta)


# T22: a failed judge request fails the row rather than aborting the run.
def test_failed_judge_request_fails_the_row(run_cli, api):
    def responder(body, i):
        if "evaluator" in body["messages"][0]["content"]:
            return 400, {"error": "bad judge request"}
        return 200, completion("answer")

    mock = api(responder)
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["result"]["passed"] is False
    assert r.rows[0]["result"]["judge_score"] is None


def test_llm_judge_requires_judge_prompt(run_cli, echo_api):
    cfg = make_config(echo_api.url,
                      evaluation={"type": "llm_judge", "threshold": 7,
                                  "extract": "first_number"})
    r = run_cli(cfg, JUDGE_ROWS)
    assert r.code == 1
    assert r.stderr.strip()


# T27: threshold is required for llm_judge.
def test_llm_judge_requires_threshold(run_cli, echo_api):
    cfg = make_config(echo_api.url,
                      evaluation={"type": "llm_judge",
                                  "judge_prompt": copy.deepcopy(JUDGE_PROMPT),
                                  "extract": "first_number"})
    r = run_cli(cfg, JUDGE_ROWS)
    assert r.code == 1
    assert r.stderr.strip()


def test_llm_judge_does_not_require_answer_field(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), [{"question": "q", "criteria": "clarity"}])
    assert r.code == 0, r.stderr


# A row whose generation failed is not judged.
def test_no_judge_call_when_generation_failed(run_cli, api):
    def responder(body, i):
        if "evaluator" in body["messages"][0]["content"]:
            return 200, completion("9")
        return 500, {"error": "boom"}

    mock = api(responder)
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS)
    assert r.code == 0, r.stderr
    assert r.rows[0]["output"] is None
    assert judge_bodies(mock) == []


# ---------------------------------------------------------------------------
# CLI Changes
# "--task <name>: repeatable; run only the selected task or tasks"
# ---------------------------------------------------------------------------

def three_task_config(url):
    return make_multi_config(url, {"gsm8k": task(GSM8K_GREEDY),
                                   "mmlu": task(MMLU),
                                   "extra": task(GSM8K_GREEDY)})


def test_task_flag_runs_only_the_selected_task(run_multi, echo_api):
    cfg = three_task_config(echo_api.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "gsm8k"])
    assert r.code == 0, r.stderr
    assert r.outputs == ["gsm8k.jsonl"]


def test_task_flag_is_repeatable(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = three_task_config(mock.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "mmlu": MMLU_ROWS},
                  args=["--task", "gsm8k", "--task", "mmlu"])
    assert r.code == 0, r.stderr
    assert r.outputs == ["gsm8k.jsonl", "mmlu.jsonl"]


def test_unselected_tasks_issue_no_requests(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = three_task_config(mock.url)
    rows = rows_n(3)
    r = run_multi(cfg, {"gsm8k": rows}, args=["--task", "gsm8k"])
    assert r.code == 0, r.stderr
    assert mock.call_count == 3


# T30: an unknown --task name is a configuration error.
def test_unknown_task_name_exits_one(run_multi, echo_api):
    cfg = three_task_config(echo_api.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "nope"])
    assert r.code == 1
    assert "nope" in r.stderr


# "--eval-model <string>: override the judge model for all selected llm_judge
#  tasks"
def test_eval_model_overrides_the_judge_model(run_multi, api):
    mock = judge_split(api, "answer", "8")
    cfg = make_multi_config(mock.url, {"review": task(REVIEW)})
    r = run_multi(cfg, {"review": REVIEW_ROWS}, args=["--eval-model", "judge-x"])
    assert r.code == 0, r.stderr
    assert judge_bodies(mock)[0]["model"] == "judge-x"
    assert gen_bodies(mock)[0]["model"] == "gpt-4"


def test_eval_model_overrides_a_configured_evaluation_model(run_multi, api):
    mock = judge_split(api, "answer", "8")
    review = task(REVIEW)
    review["evaluation"]["model"] = "configured-judge"
    cfg = make_multi_config(mock.url, {"review": review})
    r = run_multi(cfg, {"review": REVIEW_ROWS}, args=["--eval-model", "judge-x"])
    assert judge_bodies(mock)[0]["model"] == "judge-x"


def test_eval_model_applies_to_every_selected_llm_judge_task(run_multi, api):
    mock = judge_split(api, "answer", "8")
    cfg = make_multi_config(mock.url, {"review": task(REVIEW),
                                       "review2": task(REVIEW)})
    r = run_multi(cfg, {"review": REVIEW_ROWS, "review2": REVIEW_ROWS},
                  args=["--eval-model", "judge-x"])
    assert r.code == 0, r.stderr
    assert {b["model"] for b in judge_bodies(mock)} == {"judge-x"}


def test_eval_model_does_not_disturb_non_judge_tasks(run_multi, api):
    mock = judge_split(api, "#### 5", "8")
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--eval-model", "judge-x"])
    assert r.code == 0, r.stderr
    assert {b["model"] for b in mock.bodies} == {"gpt-4"}


def test_eval_model_works_for_a_single_task_config(run_cli, api):
    mock = judge_split(api, "answer", "8")
    r = run_cli(judge_cfg(mock.url), JUDGE_ROWS, args=["--eval-model", "judge-y"])
    assert r.code == 0, r.stderr
    assert judge_bodies(mock)[0]["model"] == "judge-y"


# ---------------------------------------------------------------------------
# Input handling for multi-task configs
# "explicit mapping mode: --input gsm8k=math.jsonl --input mmlu=qa.jsonl"
# ---------------------------------------------------------------------------

def test_explicit_mapping_mode_feeds_each_task_its_file(run_multi, api):
    mock = api(lambda body, i: (200, completion("The answer is B) Paris")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY), "mmlu": task(MMLU)})
    r = run_multi(cfg, {"gsm8k": rows_n(2), "mmlu": MMLU_ROWS})
    assert r.code == 0, r.stderr
    assert len(r.rows("gsm8k")) == 2
    assert len(r.rows("mmlu")) == 1
    assert r.rows("mmlu")[0]["input"]["answer"] == "B"


def test_explicit_mapping_with_an_unknown_task_name_exits_one(run_multi, echo_api, tmp_path):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    path = tmp_path / "stray.jsonl"
    path.write_text(json.dumps(MATH_ROWS[0]) + "\n")
    r = run_multi(cfg, {"gsm8k": MATH_ROWS},
                  args=["--input", "ghost=%s" % path])
    assert r.code == 1
    assert "ghost" in r.stderr


def test_missing_input_for_a_task_exits_one(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY),
                                           "mmlu": task(MMLU)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert r.code == 1
    assert "mmlu" in r.stderr


# "directory mode: --input-dir data/"
# "--input-dir looks for <task_name>.jsonl"
def test_input_dir_mode_loads_task_named_files(run_multi, api):
    mock = api(lambda body, i: (200, completion("The answer is B) Paris")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY), "mmlu": task(MMLU)})
    r = run_multi(cfg, {"gsm8k": rows_n(2), "mmlu": MMLU_ROWS}, mode="dir")
    assert r.code == 0, r.stderr
    assert len(r.rows("gsm8k")) == 2
    assert len(r.rows("mmlu")) == 1


def test_input_dir_missing_file_for_a_task_exits_one(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY),
                                           "mmlu": task(MMLU)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, mode="dir")
    assert r.code == 1
    assert "mmlu" in r.stderr


def test_input_dir_ignores_unrelated_files(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "unrelated": MATH_ROWS}, mode="dir")
    assert r.code == 0, r.stderr
    assert r.outputs == ["gsm8k.jsonl"]


# T29: a missing --input-dir is an input error.
def test_input_dir_that_does_not_exist_exits_one(run_multi, echo_api, tmp_path):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {}, mode="none",
                  args=["--input-dir", str(tmp_path / "no_such_dir")])
    assert r.code == 1


# "for multi-task configs, explicit --input <task=path> and --input-dir are
#  alternative modes; do not combine them"
def test_combining_input_and_input_dir_exits_one(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, mode="explicit")
    # re-run with both flags
    r2 = run_multi(cfg, {"gsm8k": MATH_ROWS}, mode="explicit",
                   args=["--input-dir", str(r.data_dir)])
    assert r2.code == 1
    assert r2.stderr.strip()


# T28: a multi-task config needs one of the two input modes.
def test_multi_task_config_without_any_input_exits_one(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {}, mode="none")
    assert r.code == 1


# T28: a bare --input path is meaningless for a multi-task config.
def test_multi_task_config_with_bare_input_path_exits_one(run_multi, echo_api, tmp_path):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    path = tmp_path / "bare.jsonl"
    path.write_text(json.dumps(MATH_ROWS[0]) + "\n")
    r = run_multi(cfg, {}, mode="none", args=["--input", str(path)])
    assert r.code == 1


# "when --task is present, require input only for selected tasks and ignore
#  unselected tasks for validation and execution"
def test_input_required_only_for_selected_tasks(run_multi, echo_api):
    cfg = three_task_config(echo_api.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "gsm8k"])
    assert r.code == 0, r.stderr


def test_input_dir_needs_files_only_for_selected_tasks(run_multi, echo_api):
    cfg = three_task_config(echo_api.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, mode="dir", args=["--task", "gsm8k"])
    assert r.code == 0, r.stderr
    assert r.outputs == ["gsm8k.jsonl"]


# T31: unselected tasks are skipped for config validation too.
def test_unselected_task_with_an_invalid_config_is_ignored(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {
        "gsm8k": task(GSM8K_GREEDY),
        "broken": task(GSM8K_GREEDY, generation={"scheme": "nonsense"}),
    })
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "gsm8k"])
    assert r.code == 0, r.stderr


# "for single-task configs, --input <path> without = still behaves as in Part 1"
def test_single_task_config_takes_a_bare_input_path(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert r.code == 0, r.stderr
    assert len(r.rows) == 1


# ---------------------------------------------------------------------------
# Output handling
# "for multi-task configs, --output must be a directory"
# "write <output_dir>/<task_name>.jsonl"
# ---------------------------------------------------------------------------

def test_multi_task_output_files_are_named_after_the_task(run_multi, api):
    mock = api(lambda body, i: (200, completion("The answer is B) Paris")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY), "mmlu": task(MMLU)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "mmlu": MMLU_ROWS})
    assert r.code == 0, r.stderr
    assert r.outputs == ["gsm8k.jsonl", "mmlu.jsonl"]


# T32: a missing output directory is created.
def test_multi_task_output_directory_is_created_if_absent(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, make_out_dir=False)
    assert r.code == 0, r.stderr
    assert r.path("gsm8k").is_file()


def test_multi_task_output_pointing_at_a_file_exits_one(tmp_path, echo_api):
    cfg_path = tmp_path / "multi.yaml"
    cfg_path.write_text(yaml.safe_dump(
        make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})))
    in_path = tmp_path / "gsm8k.jsonl"
    in_path.write_text(json.dumps(MATH_ROWS[0]) + "\n")
    out_path = tmp_path / "not_a_dir.jsonl"
    out_path.write_text("")
    proc = subprocess.run(
        [sys.executable, str(REJECTOR), "run", "--config", str(cfg_path),
         "--input", "gsm8k=%s" % in_path, "--output", str(out_path)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert proc.stderr.strip()


# "when --task is present, write output files only for the tasks that ran"
def test_only_selected_tasks_get_output_files(run_multi, echo_api):
    cfg = three_task_config(echo_api.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "gsm8k"])
    assert r.outputs == ["gsm8k.jsonl"]


# "for single-task configs, --output <path> still writes a single file"
def test_single_task_output_is_one_file(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert r.out_path.is_file()
    assert len(r.rows) == 1


# "for single-task configs, the stdout summary keeps its previous keys and has
#  no tasks object"
def test_single_task_summary_keys_are_unchanged(run_cli, echo_api):
    r = run_cli(make_config(echo_api.url), MATH_ROWS)
    assert set(r.summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm"}


# ---------------------------------------------------------------------------
# Summary And Scheduling
# "The stdout summary now includes a tasks object keyed by executed task name"
# ---------------------------------------------------------------------------

def test_summary_has_a_tasks_object_keyed_by_task_name(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY),
                                       "second": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": rows_n(2), "second": rows_n(3)})
    assert r.code == 0, r.stderr
    assert set(r.summary["tasks"]) == {"gsm8k", "second"}


def test_per_task_summary_keys(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    assert set(r.summary["tasks"]["gsm8k"]) == {"total", "passed", "failed",
                                                "total_api_calls"}


def test_per_task_counts(run_multi, api):
    def responder(body, i):
        # gsm8k passes, "second" fails its exact_match.
        return 200, completion("#### 5" if "step by step" in
                               body["messages"][0]["content"] else "#### 9")

    mock = api(responder)
    cfg = make_multi_config(mock.url, {
        "gsm8k": task(GSM8K_GREEDY),
        "second": task(GSM8K_GREEDY, prompt={"system": "other", "user": "{question}"}),
    })
    r = run_multi(cfg, {"gsm8k": rows_n(2), "second": rows_n(3)})
    assert r.code == 0, r.stderr
    tasks = r.summary["tasks"]
    assert tasks["gsm8k"] == {"total": 2, "passed": 2, "failed": 0,
                              "total_api_calls": 2}
    assert tasks["second"] == {"total": 3, "passed": 0, "failed": 3,
                               "total_api_calls": 3}


def test_top_level_totals_aggregate_the_tasks(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY),
                                       "second": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": rows_n(2), "second": rows_n(3)})
    s = r.summary
    assert s["total"] == 5
    assert s["passed"] + s["failed"] >= 5
    assert s["total_api_calls"] == sum(t["total_api_calls"]
                                       for t in s["tasks"].values())
    assert s["total"] == sum(t["total"] for t in s["tasks"].values())


# "include only tasks that actually ran"
def test_summary_omits_tasks_that_did_not_run(run_multi, echo_api):
    cfg = three_task_config(echo_api.url)
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "gsm8k"])
    assert set(r.summary["tasks"]) == {"gsm8k"}


def test_multi_task_summary_keeps_the_part_one_keys(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    for key in ("total", "passed", "failed", "total_api_calls",
                "elapsed_seconds", "throughput_rpm"):
        assert key in r.summary


# "per-task total_api_calls includes judge calls"
def test_per_task_api_calls_include_judge_and_retries(run_multi, api):
    state = {"n": 0}

    def responder(body, i):
        if "evaluator" in body["messages"][0]["content"]:
            return 200, completion("9")
        state["n"] += 1
        if state["n"] == 1:
            return 500, {"error": "boom"}
        return 200, completion("answer")

    mock = judge_split(api, "answer", "9")
    mock.stop()
    mock = api(responder)
    cfg = make_multi_config(mock.url, {"review": task(REVIEW)})
    r = run_multi(cfg, {"review": REVIEW_ROWS})
    assert r.code == 0, r.stderr
    # one retried generation (2 calls) plus one judge call
    assert r.summary["tasks"]["review"]["total_api_calls"] == 3


# "requests from different tasks may run concurrently and may be interleaved"
def test_requests_from_different_tasks_are_interleaved(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")), delay=0.2)
    cfg = make_multi_config(mock.url, {
        "alpha": task(GSM8K_GREEDY, prompt={"system": "SYS-A", "user": "{question}"}),
        "beta": task(GSM8K_GREEDY, prompt={"system": "SYS-B", "user": "{question}"}),
    })
    r = run_multi(cfg, {"alpha": rows_n(6), "beta": rows_n(6)})
    assert r.code == 0, r.stderr
    assert mock.max_inflight > 1
    with mock.lock:
        spans = {}
        for req in mock.requests:
            key = req["body"]["messages"][0]["content"]
            start, end = req["t_start"], req["t_end"]
            lo, hi = spans.get(key, (start, end))
            spans[key] = (min(lo, start), max(hi, end))
    assert set(spans) == {"SYS-A", "SYS-B"}
    a, b = spans["SYS-A"], spans["SYS-B"]
    # The two tasks' request windows overlap: neither waits for the other.
    assert min(a[1], b[1]) > max(a[0], b[0])


# "within each task's output file, row order must still match input order"
def test_row_order_matches_input_order_per_task(run_multi, api):
    def responder(body, i):
        return 200, completion("#### 5")

    mock = api(responder, delay=0.05)
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY),
                                       "second": task(GSM8K_GREEDY)})
    a = [dict(MATH_ROWS[0], question="a%d" % i) for i in range(8)]
    b = [dict(MATH_ROWS[0], question="b%d" % i) for i in range(8)]
    r = run_multi(cfg, {"gsm8k": a, "second": b})
    assert r.code == 0, r.stderr
    assert [row["input"]["question"] for row in r.rows("gsm8k")] == \
        [row["question"] for row in a]
    assert [row["input"]["question"] for row in r.rows("second")] == \
        [row["question"] for row in b]


# ---------------------------------------------------------------------------
# Examples
# MMLU-style extraction: the model returns "The answer is B) Paris", letter
# extracts "B" and the row passes.
# ---------------------------------------------------------------------------

def test_spec_mmlu_example(run_multi, api):
    mock = api(lambda body, i: (200, completion("The answer is B) Paris")))
    cfg = make_multi_config(mock.url, {"mmlu": task(MMLU)})
    r = run_multi(cfg, {"mmlu": MMLU_ROWS})
    assert r.code == 0, r.stderr
    row = r.rows("mmlu")[0]
    assert row["result"]["extracted_answer"] == "B"
    assert row["result"]["passed"] is True
    assert row["output"] == {"choice": "The answer is B) Paris"}
    user = gen_bodies(mock)[0]["messages"][1]["content"]
    assert user == ("What is the capital of France?\n\n"
                    "A) London\nB) Paris\nC) Berlin\nD) Madrid")


# LLM judge example: "if the judge returns \"8\", then judge_score is 8; with
# threshold: 7, the row passes; meta.judge_meta records the judge call
# metadata"
def test_spec_llm_judge_example(run_multi, api):
    mock = judge_split(api, "The sea is vast and blue.", "8")
    cfg = make_multi_config(mock.url, {"review": task(REVIEW)})
    r = run_multi(cfg, {"review": REVIEW_ROWS})
    assert r.code == 0, r.stderr
    row = r.rows("review")[0]
    assert row["output"] == {"response": "The sea is vast and blue."}
    assert row["result"]["judge_score"] == 8
    assert row["result"]["extracted_answer"] == "8"
    assert row["result"]["passed"] is True
    assert row["meta"]["judge_meta"]["model"] == "gpt-4"
    judge_user = judge_bodies(mock)[0]["messages"][1]["content"]
    assert "Original prompt: Describe the sea." in judge_user
    assert "The sea is vast and blue." in judge_user
    assert "Criteria: clarity" in judge_user


# Script evaluation example: the row's test_code embeds {__response__}; a zero
# exit code passes, non-zero fails.
def test_spec_script_example(run_multi, api):
    mock = api(lambda body, i: (200, completion("this is good code")))
    cfg = make_multi_config(mock.url, {"code_gen": task(CODE_GEN)})
    r = run_multi(cfg, {"code_gen": CODE_ROWS})
    assert r.code == 0, r.stderr
    assert r.rows("code_gen")[0]["result"]["passed"] is True


def test_spec_script_example_failing_response(run_multi, api):
    mock = api(lambda body, i: (200, completion("nothing useful")))
    cfg = make_multi_config(mock.url, {"code_gen": task(CODE_GEN)})
    r = run_multi(cfg, {"code_gen": CODE_ROWS})
    assert r.rows("code_gen")[0]["result"]["passed"] is False


# "Only gsm8k runs. Input files for unselected tasks are not required."
def test_spec_selected_task_run(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY),
                                       "mmlu": task(MMLU),
                                       "review": task(REVIEW)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS}, args=["--task", "gsm8k"])
    assert r.code == 0, r.stderr
    assert r.outputs == ["gsm8k.jsonl"]
    assert set(r.summary["tasks"]) == {"gsm8k"}


# The spec's canonical four-task config parses and runs end to end.
def test_spec_canonical_multi_task_config(run_multi, api):
    def responder(body, i):
        system = body["messages"][0]["content"]
        if "evaluator" in system:
            return 200, completion("8")
        if "multiple choice" in system:
            return 200, completion("The answer is B) Paris")
        if "Python function" in system:
            return 200, completion("this is good code")
        if "writing assistant" in system:
            return 200, completion("A thoughtful response.")
        return 200, completion("#### 5")

    mock = api(responder)
    cfg = make_multi_config(mock.url, {
        "gsm8k": task(GSM8K),
        "mmlu": task(MMLU),
        "code_gen": task(CODE_GEN),
        "review": task(REVIEW),
    })
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "mmlu": MMLU_ROWS,
                        "code_gen": CODE_ROWS, "review": REVIEW_ROWS})
    assert r.code == 0, r.stderr
    assert sorted(r.summary["tasks"]) == ["code_gen", "gsm8k", "mmlu", "review"]
    for name in ("gsm8k", "mmlu", "code_gen", "review"):
        assert r.rows(name)[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# "Existing behavior from Part 1 is unchanged unless stated here."
# ---------------------------------------------------------------------------

def test_part_one_row_shape_is_unchanged_for_multi_task_rows(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS})
    row = r.rows("gsm8k")[0]
    assert set(row) == {"input", "output", "result", "meta"}
    assert set(row["result"]) == {"passed", "extracted_answer", "attempts"}


def test_part_one_cli_overrides_apply_to_every_selected_task(run_multi, api):
    mock = api(lambda body, i: (200, completion("#### 5")))
    cfg = make_multi_config(mock.url, {"gsm8k": task(GSM8K_GREEDY),
                                       "second": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": MATH_ROWS, "second": MATH_ROWS},
                  args=["--max-tokens", "99", "--model", "override-model"])
    assert r.code == 0, r.stderr
    assert {b["max_tokens"] for b in mock.bodies} == {99}
    assert {b["model"] for b in mock.bodies} == {"override-model"}


def test_part_one_row_validation_still_applies_per_task(run_multi, echo_api):
    cfg = make_multi_config(echo_api.url, {"gsm8k": task(GSM8K_GREEDY)})
    r = run_multi(cfg, {"gsm8k": [{"text": "hello", "answer": "5"}]})
    assert r.code == 1
    assert "question" in r.stderr

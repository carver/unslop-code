"""Part 2 configuration: `defaults` + `tasks`, merging, and the Part 1 form."""
import json

import pytest
import yaml

from conftest import make_multi_config, judge_task, make_config
from mock_api import MockAPI, always, per_question, message_text

import rejector


GSM = [{"question": "2+2?", "answer": "4"}]
MML = [{"question": "capital?", "answer": "B"}]


# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Configuration. Each task has its own prompt, generation settings,
# evaluation, and output field.
def test_multi_task_config_runs_every_task(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B) Paris"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert run.rows("gsm8k")[0]["result"]["passed"] is True
    assert run.rows("mmlu")[0]["result"]["passed"] is True


# Spec: "Each task has its own prompt, generation settings, evaluation, and
# output field."
def test_each_task_uses_its_own_output_field(multi):
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert list(run.rows("gsm8k")[0]["output"]) == ["solution"]
    assert list(run.rows("mmlu")[0]["output"]) == ["choice"]


def test_each_task_uses_its_own_prompt(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    systems = sorted(message_text(c, "system") for c in api.calls)
    assert systems == ["Answer with a single letter.", "Solve the math problem."]


# Spec: "`defaults` provides shared values; each task overrides `defaults`"
# Context: Rules.
def test_task_inherits_scalar_values_from_defaults(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(make_multi_config(api_url=api.url),
                        {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    assert {c["model"] for c in api.calls} == {"gpt-4"}


def test_task_value_overrides_the_default(multi):
    cfg = make_multi_config()
    cfg["tasks"]["mmlu"]["model"] = "gpt-4o-mini"
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    models = {message_text(c, "user"): c["model"] for c in api.calls}
    assert models["2+2?"] == "gpt-4"
    assert models["capital?"] == "gpt-4o-mini"


# Spec: "nested sections such as `prompt`, `generation`, and `evaluation` are
# merged per task using the Part 1 structure"
# Context: Rules. A task's `generation` block keeps default keys it omits.
def test_generation_keys_merge_with_defaults(multi):
    cfg = make_multi_config(defaults={"generation": {"max_tokens": 77}})
    with MockAPI(always("#### 4")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    # tasks only set `scheme`, so `max_tokens` still comes from defaults.
    assert {c["max_tokens"] for c in api.calls} == {77}


def test_task_generation_key_beats_the_default_key(multi):
    cfg = make_multi_config(defaults={"generation": {"max_tokens": 77}})
    cfg["tasks"]["gsm8k"]["generation"]["max_tokens"] = 12
    with MockAPI(per_question({"2+2?": "#### 4", "capital?": "B"})) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 0, run.stderr
    tokens = {message_text(c, "user"): c["max_tokens"] for c in api.calls}
    assert tokens["2+2?"] == 12
    assert tokens["capital?"] == 77


def test_prompt_section_merges_system_from_defaults(multi):
    cfg = make_multi_config(defaults={"prompt": {"system": "SHARED SYSTEM"}})
    del cfg["tasks"]["gsm8k"]["prompt"]["system"]
    with MockAPI(always("#### 4")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    assert message_text(api.calls[0], "system") == "SHARED SYSTEM"


def test_evaluation_section_merges_with_defaults(multi):
    cfg = make_multi_config(
        defaults={"evaluation": {"type": "exact_match", "answer_field": "answer"}})
    cfg["tasks"]["gsm8k"]["evaluation"] = {"extract": "last_number"}
    with MockAPI(always("#### 4")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"gsm8k": GSM}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    row = run.rows("gsm8k")[0]
    assert row["result"]["extracted_answer"] == "4"
    assert row["result"]["passed"] is True


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task"
# Context: Rules.
def test_required_field_supplied_only_by_the_task_is_accepted(multi):
    cfg = make_multi_config()
    with MockAPI(always("#### 4")) as api:
        del cfg["defaults"]["model"]
        cfg["defaults"]["api_url"] = api.url
        cfg["tasks"]["gsm8k"]["model"] = "task-model"
        run = multi.run(cfg, {"gsm8k": GSM}, args=["--task", "gsm8k"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["model"] == "task-model"


def test_missing_required_field_in_both_places_exits_1(multi):
    cfg = make_multi_config()
    del cfg["defaults"]["model"]
    run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 1
    assert run.stderr.strip()


def test_missing_prompt_user_exits_1(multi):
    cfg = make_multi_config()
    del cfg["tasks"]["mmlu"]["prompt"]["user"]
    run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 1
    assert run.stderr.strip()


def test_invalid_scheme_in_one_task_exits_1(multi):
    cfg = make_multi_config()
    cfg["tasks"]["mmlu"]["generation"]["scheme"] = "beam"
    run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 1
    assert run.stderr.strip()


# Part 1 rule, still enforced per task: rejection needs a positive temperature.
def test_rejection_without_temperature_exits_1(multi):
    cfg = make_multi_config()
    cfg["tasks"]["gsm8k"]["generation"] = {"scheme": "rejection", "n": 3}
    run = multi.run(cfg, {"gsm8k": GSM, "mmlu": MML})
    assert run.returncode == 1


# Spec: "if the config still uses a top-level `task` key, treat it as the Part
# 1 single-task format; the task name is `task.name`"
# Context: Rules.
def test_top_level_task_key_is_single_task_format(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert len(run.rows) == 1
    assert run.rows[0]["output"] == {"solution": "#### 5"}


def test_single_task_name_comes_from_task_name(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url, name="my_task"),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert list(run.summary["tasks"]) == ["my_task"]


# T19: a config carrying both keys is read as the Part 1 single-task format.
def test_task_key_wins_over_tasks_key(run_tool):
    config = make_config()
    config["tasks"] = {"other": {"prompt": {"user": "{question}"}}}
    with MockAPI(always("#### 5")) as api:
        config["task"]["api_url"] = api.url
        run = run_tool(config, [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert list(run.summary["tasks"]) == ["gsm8k_solve"]


def test_config_with_neither_task_nor_tasks_exits_1(run_tool):
    run = run_tool(config_text="defaults:\n  model: gpt-4\n",
                   rows=[{"question": "q", "answer": "5"}])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_empty_tasks_mapping_exits_1(multi):
    run = multi.run({"defaults": {"model": "gpt-4"}, "tasks": {}}, {})
    assert run.returncode == 1


# The full four-task config shape from the spec must validate.
def test_spec_example_config_validates(multi, tmp_path):
    cfg = yaml.safe_load(SPEC_CONFIG)
    multi_ok, specs = rejector.split_config(cfg)
    assert multi_ok
    assert [name for name, _ in specs] == ["gsm8k", "mmlu", "code_gen", "review"]
    args = _args()
    for name, task in specs:
        built = rejector.build_task_config(task, args, name, True)
        assert built.api_url == "http://localhost:8000"
        assert built.model == "gpt-4"
        assert built.rpm == 60
        assert built.max_tokens == 512


def _args(**kw):
    class Args(object):
        pass
    args = Args()
    for key in ("api_url", "model", "rpm", "scheme", "temperature",
                "max_tokens", "n", "eval_model"):
        setattr(args, key, kw.get(key))
    return args


SPEC_CONFIG = """
defaults:
  api_url: "http://localhost:8000"
  model: "gpt-4"
  rpm: 60
  generation:
    max_tokens: 512

tasks:
  gsm8k:
    prompt:
      system: "Solve the math problem step by step. Put your final answer after ####."
      user: "{question}"
    generation:
      scheme: "rejection"
      temperature: 0.7
      n: 5
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"

  mmlu:
    prompt:
      system: "Answer the multiple choice question with a single letter."
      user: "{question}\\n\\nA) {a}\\nB) {b}\\nC) {c}\\nD) {d}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "letter"
    output_field: "choice"

  code_gen:
    prompt:
      system: "Write a Python function to solve the problem."
      user: "{problem}"
    generation:
      scheme: "rejection"
      temperature: 0.8
      n: 3
    evaluation:
      type: "script"
      command_template: "python3 -c \\"{test_code}\\""
      success_exit_code: 0
    output_field: "code"

  review:
    prompt:
      system: "You are a writing assistant."
      user: "{prompt_text}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "You are a quality evaluator."
        user: "Rate: {__response__}\\n\\nCriteria: {criteria}\\n\\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"
"""

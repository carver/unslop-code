"""Multi-task config shape: `defaults` + `tasks`, merging, and required fields."""

from __future__ import annotations

import pytest

from conftest import base_defaults, choice_task, judge_task, math_task, script_task

from taskrunner.config import ConfigError, build_run_config


def build(document: dict, **overrides):
    return build_run_config(document, overrides)


# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Configuration; the spec's four-task example.
def test_multi_task_config_parses_every_task():
    config = build(
        {
            "defaults": base_defaults("http://localhost:8000"),
            "tasks": {
                "gsm8k": math_task(),
                "mmlu": choice_task(),
                "code_gen": script_task(),
                "review": judge_task(),
            },
        }
    )
    assert list(config.tasks) == ["gsm8k", "mmlu", "code_gen", "review"]
    assert config.tasks["gsm8k"].output_field == "solution"
    assert config.tasks["mmlu"].evaluation.extract == "letter"
    assert config.tasks["code_gen"].evaluation.type == "script"
    assert config.tasks["review"].evaluation.type == "llm_judge"


# Spec: "Each task has its own prompt, generation settings, evaluation, and
# output field."
# Context: intro.
def test_each_task_keeps_its_own_sections():
    config = build(
        {
            "defaults": base_defaults("http://localhost:8000"),
            "tasks": {"gsm8k": math_task(), "mmlu": choice_task()},
        }
    )
    gsm8k, mmlu = config.tasks["gsm8k"], config.tasks["mmlu"]
    assert gsm8k.prompt.user == "{question}"
    assert mmlu.prompt.user.startswith("{question}\n\nA) {a}")
    assert (gsm8k.output_field, mmlu.output_field) == ("solution", "choice")


# Spec: "`defaults` provides shared values; each task overrides `defaults`"
# Context: Configuration / Rules.
def test_defaults_are_shared_and_task_values_win():
    config = build(
        {
            "defaults": base_defaults("http://localhost:8000", model="gpt-4", rpm=60),
            "tasks": {
                "a": math_task(),
                "b": math_task(model="gpt-4o-mini", rpm=120),
            },
        }
    )
    assert (config.tasks["a"].model, config.tasks["a"].limits.rpm) == ("gpt-4", 60)
    assert (config.tasks["b"].model, config.tasks["b"].limits.rpm) == ("gpt-4o-mini", 120)
    assert config.tasks["b"].api_url == "http://localhost:8000"


# Spec: "nested sections such as `prompt`, `generation`, and `evaluation` are
# merged per task using the Part 1 structure"
# Context: Configuration / Rules; see AMBIGUITIES T18.
def test_nested_sections_merge_key_by_key():
    config = build(
        {
            "defaults": {
                "api_url": "http://localhost:8000",
                "model": "gpt-4",
                "generation": {"max_tokens": 512, "scheme": "greedy"},
                "prompt": {"system": "shared system"},
                "evaluation": {"type": "exact_match", "extract": "full"},
                "output_field": "out",
            },
            "tasks": {
                "a": {
                    "prompt": {"user": "{question}"},
                    "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5},
                    "evaluation": {"answer_field": "answer", "extract": "last_number"},
                }
            },
        }
    )
    task = config.tasks["a"]
    assert task.prompt.system == "shared system"
    assert task.generation.max_tokens == 512
    assert (task.generation.scheme, task.generation.n) == ("rejection", 5)
    assert (task.evaluation.type, task.evaluation.extract) == ("exact_match", "last_number")
    assert task.output_field == "out"


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task"
# Context: Configuration / Rules.
def test_required_field_may_come_from_defaults():
    config = build(
        {
            "defaults": {"api_url": "http://localhost:8000", "model": "gpt-4", "output_field": "solution"},
            "tasks": {"a": {"prompt": {"user": "{question}"}}},
        }
    )
    assert config.tasks["a"].output_field == "solution"


def test_missing_required_field_in_both_places_is_an_error():
    with pytest.raises(ConfigError):
        build(
            {
                "defaults": {"model": "gpt-4"},
                "tasks": {"a": math_task()},
            }
        )


def test_missing_output_field_is_an_error():
    task = math_task()
    del task["output_field"]
    with pytest.raises(ConfigError):
        build({"defaults": base_defaults("http://localhost:8000"), "tasks": {"a": task}})


# Spec: "if the config still uses a top-level `task` key, treat it as the Part 1
# single-task format; the task name is `task.name`"
# Context: Configuration / Rules.
def test_top_level_task_key_is_single_task_format():
    from conftest import base_task

    config = build({"task": base_task("http://localhost:8000")})
    assert config.multi is False
    assert list(config.tasks) == ["gsm8k_solve"]
    assert config.tasks["gsm8k_solve"].name == "gsm8k_solve"


# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping"
# Context: Configuration; `defaults` is not required when tasks are complete.
def test_defaults_section_is_optional():
    config = build({"tasks": {"a": math_task(api_url="http://localhost:8000", model="gpt-4")}})
    assert config.multi is True
    assert config.tasks["a"].model == "gpt-4"


# Spec: multi-task task names key the `tasks` mapping.
# Context: Configuration; the key is the task's name.
def test_task_name_comes_from_the_mapping_key():
    config = build(
        {"defaults": base_defaults("http://localhost:8000"), "tasks": {"gsm8k": math_task()}}
    )
    assert config.tasks["gsm8k"].name == "gsm8k"

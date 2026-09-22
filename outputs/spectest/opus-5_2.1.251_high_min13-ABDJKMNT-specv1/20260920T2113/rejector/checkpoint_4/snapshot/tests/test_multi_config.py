"""Multi-task config loading: `defaults` + `tasks`, merging, and selection."""

from __future__ import annotations

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import multi_config, task_config


def load(cli, config, selected=None, **overrides):
    return load_config(cli.write_config(config), overrides, selected)


# "Multi-task configs use `defaults` plus a `tasks` mapping"
def test_every_task_in_the_mapping_is_loaded(cli):
    run_config = load(cli, multi_config("gsm8k", "mmlu", "code_gen", "review"))
    assert list(run_config.tasks) == ["gsm8k", "mmlu", "code_gen", "review"]
    assert run_config.multi is True


# "Multi-task configs use `defaults` plus a `tasks` mapping" - each task keeps
# "its own prompt, generation settings, evaluation, and output field"
def test_each_task_keeps_its_own_sections(cli):
    tasks = load(cli, multi_config("gsm8k", "mmlu")).tasks
    assert tasks["gsm8k"].user_prompt == "{question}"
    assert tasks["gsm8k"].generation.scheme == "rejection"
    assert tasks["gsm8k"].generation.n == 5
    assert tasks["gsm8k"].evaluation.extract == "last_number"
    assert tasks["gsm8k"].output_field == "solution"
    assert tasks["mmlu"].generation.scheme == "greedy"
    assert tasks["mmlu"].evaluation.extract == "letter"
    assert tasks["mmlu"].output_field == "choice"


# "the task name is the key in the `tasks` mapping"
def test_task_name_comes_from_the_mapping_key(cli):
    tasks = load(cli, multi_config("gsm8k", "mmlu")).tasks
    assert [task.name for task in tasks.values()] == ["gsm8k", "mmlu"]


# "`defaults` provides shared values; each task overrides `defaults`"
def test_defaults_are_shared_across_tasks(cli):
    tasks = load(cli, multi_config("gsm8k", "mmlu")).tasks
    assert [task.api_url for task in tasks.values()] == ["http://localhost:8000"] * 2
    assert [task.model for task in tasks.values()] == ["gpt-4"] * 2
    assert [task.rpm for task in tasks.values()] == [60, 60]


# "`defaults` provides shared values; each task overrides `defaults`"
def test_task_values_override_defaults(cli):
    config = multi_config("gsm8k", "mmlu")
    config["tasks"]["mmlu"]["model"] = "gpt-4o-mini"
    config["tasks"]["mmlu"]["rpm"] = 120
    tasks = load(cli, config).tasks
    assert (tasks["mmlu"].model, tasks["mmlu"].rpm) == ("gpt-4o-mini", 120)
    assert (tasks["gsm8k"].model, tasks["gsm8k"].rpm) == ("gpt-4", 60)


# "nested sections such as `prompt`, `generation`, and `evaluation` are merged
#  per task using the Part 1 structure"
def test_nested_sections_merge_instead_of_replacing(cli):
    # defaults carry generation.max_tokens only; the task carries scheme/temperature/n
    tasks = load(cli, multi_config("gsm8k")).tasks
    assert tasks["gsm8k"].generation.max_tokens == 512
    assert tasks["gsm8k"].generation.temperature == 0.7


# "nested sections such as `prompt`, `generation`, and `evaluation` are merged"
def test_prompt_and_evaluation_sections_merge_with_defaults(cli):
    config = multi_config(
        "gsm8k",
        defaults={
            "prompt": {"system": "shared system prompt"},
            "evaluation": {"answer_field": "answer"},
        },
    )
    del config["tasks"]["gsm8k"]["evaluation"]["answer_field"]
    config["tasks"]["gsm8k"]["prompt"] = {"user": "{question}"}
    task = load(cli, config).tasks["gsm8k"]
    assert task.system_prompt == "shared system prompt"
    assert task.evaluation.answer_field == "answer"


# "required Part 1 fields must still come from either `defaults` or the task"
def test_required_field_may_come_from_the_task(cli):
    config = multi_config("gsm8k")
    del config["defaults"]["model"]
    config["tasks"]["gsm8k"]["model"] = "gpt-4o"
    assert load(cli, config).tasks["gsm8k"].model == "gpt-4o"


# "required Part 1 fields must still come from either `defaults` or the task"
@pytest.mark.parametrize("missing", ["api_url", "model"])
def test_missing_required_field_is_an_error(cli, missing):
    config = multi_config("gsm8k")
    del config["defaults"][missing]
    with pytest.raises(ConfigError, match=missing):
        load(cli, config)


# "required Part 1 fields must still come from either `defaults` or the task"
# (output_field and prompt.user have no default source)
@pytest.mark.parametrize("missing", ["output_field", "prompt"])
def test_missing_task_level_required_field_is_an_error(cli, missing):
    config = multi_config("gsm8k")
    del config["tasks"]["gsm8k"][missing]
    with pytest.raises(ConfigError):
        load(cli, config)


# "if the config still uses a top-level `task` key, treat it as the Part 1
#  single-task format; the task name is `task.name`"
def test_single_task_config_still_loads(cli):
    run_config = load(cli, task_config())
    assert run_config.multi is False
    assert list(run_config.tasks) == ["math_solve"]
    assert run_config.only.output_field == "solution"


# "if the config still uses a top-level `task` key, treat it as the Part 1
#  single-task format" (a `task` key wins over any `tasks` mapping)
def test_top_level_task_key_takes_precedence(cli):
    config = {**task_config(), **multi_config("gsm8k")}
    assert load(cli, config).multi is False


# "--task <name>: repeatable; run only the selected task or tasks"
def test_selection_keeps_only_the_named_tasks(cli):
    run_config = load(cli, multi_config("gsm8k", "mmlu", "review"), selected=["mmlu", "review"])
    assert list(run_config.tasks) == ["mmlu", "review"]


# "--task <name>" naming a task the config does not define
def test_unknown_selected_task_is_an_error(cli):
    with pytest.raises(ConfigError, match="nope"):
        load(cli, multi_config("gsm8k"), selected=["nope"])


# "when `--task` is present, ... ignore unselected tasks for validation"
def test_unselected_tasks_are_not_validated(cli):
    config = multi_config("gsm8k")
    config["tasks"]["broken"] = {"prompt": {"user": "{x}"}}
    assert list(load(cli, config, selected=["gsm8k"]).tasks) == ["gsm8k"]


# Part 1 overrides apply to every selected task of a multi-task config
def test_cli_overrides_apply_to_all_tasks(cli):
    tasks = load(cli, multi_config("gsm8k", "mmlu"), model="gpt-5", rpm=30).tasks
    assert {task.model for task in tasks.values()} == {"gpt-5"}
    assert {task.rpm for task in tasks.values()} == {30}


# "--eval-model <string>: override the judge model for all selected
#  `llm_judge` tasks"
def test_eval_model_override_applies_to_judge_tasks_only(cli):
    tasks = load(cli, multi_config("gsm8k", "review"), eval_model="judge-9").tasks
    assert tasks["review"].evaluation.judge.model == "judge-9"
    assert tasks["gsm8k"].model == "gpt-4"

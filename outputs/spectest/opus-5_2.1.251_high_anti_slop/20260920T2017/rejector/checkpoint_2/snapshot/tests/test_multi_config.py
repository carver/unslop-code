"""Defaults merging, task selection, and the new evaluation types."""

import pytest
import yaml

from config import load_config, overrides_from_flags
from errors import ConfigError

DEFAULTS = {
    "api_url": "http://localhost:8000",
    "model": "gpt-4",
    "rpm": 60,
    "generation": {"max_tokens": 512},
}
TASKS = {
    "gsm8k": {
        "prompt": {"system": "Solve it.", "user": "{question}"},
        "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    },
    "review": {
        "prompt": {"system": "Write.", "user": "{prompt_text}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {"system": "Rate it.", "user": "{__response__}"},
            "threshold": 7,
        },
        "output_field": "response",
    },
}


def write_config(tmp_path, defaults=None, tasks=None):
    path = tmp_path / "multi.yaml"
    document = {"defaults": defaults or DEFAULTS, "tasks": tasks or TASKS}
    path.write_text(yaml.safe_dump(document))
    return str(path)


def by_name(config):
    return {task.name: task for task in config.tasks}


def test_tasks_inherit_and_override_defaults(tmp_path):
    tasks = by_name(load_config(write_config(tmp_path)))

    assert list(tasks) == ["gsm8k", "review"]
    assert tasks["gsm8k"].api_url == "http://localhost:8000"
    assert tasks["gsm8k"].generation.max_tokens == 512, "inherited from defaults"
    assert tasks["gsm8k"].generation.n == 5
    assert tasks["review"].generation.scheme == "greedy"


def test_a_task_overrides_a_default_value(tmp_path):
    tasks = {**TASKS, "gsm8k": {**TASKS["gsm8k"], "model": "gpt-4o", "generation": {"scheme": "greedy"}}}
    loaded = by_name(load_config(write_config(tmp_path, tasks=tasks)))

    assert loaded["gsm8k"].model == "gpt-4o"
    assert loaded["gsm8k"].generation.max_tokens == 512, "nested sections merge, not replace"
    assert loaded["review"].model == "gpt-4"


def test_required_fields_may_come_from_either_layer(tmp_path):
    defaults = {key: value for key, value in DEFAULTS.items() if key != "model"}
    with pytest.raises(ConfigError, match="tasks.gsm8k.model is required"):
        load_config(write_config(tmp_path, defaults=defaults))

    tasks = {name: {**body, "model": "gpt-4"} for name, body in TASKS.items()}
    assert by_name(load_config(write_config(tmp_path, defaults=defaults, tasks=tasks)))["gsm8k"].model == "gpt-4"


def test_selection_keeps_only_the_named_tasks(tmp_path):
    config = load_config(write_config(tmp_path), selected=["review"])
    assert [task.name for task in config.tasks] == ["review"]


def test_selection_ignores_problems_in_unselected_tasks(tmp_path):
    tasks = {**TASKS, "review": {"output_field": "response"}}
    config = load_config(write_config(tmp_path, tasks=tasks), selected=["gsm8k"])
    assert [task.name for task in config.tasks] == ["gsm8k"]


def test_unknown_selected_task_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="has no task named 'mmlu'"):
        load_config(write_config(tmp_path), selected=["mmlu"])


def test_judge_defaults_to_the_task_model_and_numeric_extraction(tmp_path):
    evaluation = by_name(load_config(write_config(tmp_path)))["review"].evaluation
    assert (evaluation.model, evaluation.extract) == ("gpt-4", "first_number")
    assert evaluation.threshold == 7.0
    assert evaluation.judge_prompt.system == "Rate it."


def test_eval_model_override_only_touches_evaluations(tmp_path):
    overrides = overrides_from_flags({"eval_model": "judge-model", "model": "gen-model"})
    tasks = {**TASKS, "plain": {**TASKS["review"], "evaluation": None}}
    loaded = by_name(load_config(write_config(tmp_path, tasks=tasks), overrides))

    assert loaded["review"].evaluation.model == "judge-model"
    assert loaded["review"].model == "gen-model"
    assert loaded["plain"].evaluation is None


def test_judge_requires_its_prompt_and_threshold(tmp_path):
    evaluation = {"type": "llm_judge", "threshold": 7}
    tasks = {"review": {**TASKS["review"], "evaluation": evaluation}}
    with pytest.raises(ConfigError, match="judge_prompt is required"):
        load_config(write_config(tmp_path, tasks=tasks))


def test_script_requires_a_command_template(tmp_path):
    tasks = {"code": {**TASKS["gsm8k"], "evaluation": {"type": "script"}}}
    with pytest.raises(ConfigError, match="command_template is required"):
        load_config(write_config(tmp_path, tasks=tasks))


def test_script_exit_code_defaults_to_zero(tmp_path):
    evaluation = {"type": "script", "command_template": "true"}
    tasks = {"code": {**TASKS["gsm8k"], "evaluation": evaluation}}
    code = by_name(load_config(write_config(tmp_path, tasks=tasks)))["code"].evaluation
    assert code.success_exit_code == 0


def test_config_without_task_or_tasks_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"defaults": DEFAULTS}))
    with pytest.raises(ConfigError, match="must contain a 'task' or 'tasks' mapping"):
        load_config(str(path))

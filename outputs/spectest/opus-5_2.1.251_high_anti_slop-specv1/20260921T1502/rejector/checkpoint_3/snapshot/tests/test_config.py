"""Configuration loading and validation."""

from copy import deepcopy

import pytest
import yaml

from config import load_config
from errors import UsageError

BASE = {
    "name": "demo",
    "api_url": "http://localhost:8000/",
    "model": "gpt-4",
    "rpm": 60,
    "prompt": {"system": "solve", "user": "{question}"},
    "generation": {"scheme": "greedy", "temperature": 0.7, "max_tokens": 256},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}


def write(tmp_path, **task):
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": {**BASE, **task}}))
    return path


def load(tmp_path, overrides=None, **task):
    """Load a single task config, which always yields a one task suite."""
    suite = load_config(write(tmp_path, **task), overrides or {})
    assert not suite.multi
    return suite.tasks[0]


def test_greedy_forces_zero_temperature(tmp_path):
    config = load(tmp_path)
    assert config.generation.temperature == 0.0
    assert config.api_url == "http://localhost:8000"


def test_cli_overrides_replace_config_values(tmp_path):
    config = load(
        tmp_path,
        {"scheme": "sample", "temperature": 0.9, "rpm": 120, "model": "other", "n": 4},
    )
    assert (config.generation.scheme, config.generation.temperature) == ("sample", 0.9)
    assert (config.rpm, config.model, config.generation.n) == (120, "other", 4)


def test_sample_requires_positive_temperature(tmp_path):
    with pytest.raises(UsageError, match="temperature must be > 0"):
        load(tmp_path, generation={"scheme": "sample", "temperature": 0.0})


def test_rejection_requires_evaluation(tmp_path):
    with pytest.raises(UsageError, match="evaluation is required"):
        load(tmp_path, generation={"scheme": "rejection", "temperature": 0.7}, evaluation=None)


def test_unknown_scheme_is_rejected(tmp_path):
    with pytest.raises(UsageError, match="scheme must be one of"):
        load(tmp_path, generation={"scheme": "beam"})


def test_regex_evaluation_requires_a_pattern(tmp_path):
    with pytest.raises(UsageError, match="pattern is required"):
        load(tmp_path, evaluation={"type": "regex"})


def test_regex_evaluation_does_not_need_an_answer_field(tmp_path):
    config = load(tmp_path, evaluation={"type": "regex", "pattern": r"####\s*(\d+)"})
    assert config.evaluation.answer_field is None


def test_contains_evaluation_requires_an_answer_field(tmp_path):
    with pytest.raises(UsageError, match="answer_field is required"):
        load(tmp_path, evaluation={"type": "contains"})


def test_missing_required_key_is_reported(tmp_path):
    with pytest.raises(UsageError, match="task.output_field is required"):
        load(tmp_path, output_field=None)


def test_invalid_yaml_is_reported(tmp_path):
    path = tmp_path / "task.yaml"
    path.write_text("task: [1, 2\n")
    with pytest.raises(UsageError, match="invalid YAML"):
        load_config(path, {})


MULTI = {
    "defaults": {
        "api_url": "http://localhost:8000",
        "model": "gpt-4",
        "rpm": 60,
        "generation": {"max_tokens": 512},
    },
    "tasks": {
        "gsm8k": {
            "prompt": {"system": "solve", "user": "{question}"},
            "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5},
            "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
            "output_field": "solution",
        },
        "review": {
            "prompt": {"user": "{prompt_text}"},
            "generation": {"scheme": "greedy"},
            "evaluation": {
                "type": "llm_judge",
                "judge_prompt": {"system": "rate it", "user": "{__response__}"},
                "threshold": 7,
                "extract": "first_number",
            },
            "output_field": "response",
        },
    },
}


def load_multi(tmp_path, overrides=None, selected=(), document=None):
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump(document or MULTI))
    return load_config(path, overrides or {}, selected)


def test_tasks_inherit_and_override_defaults(tmp_path):
    suite = load_multi(tmp_path)
    gsm8k, review = suite.tasks

    assert suite.multi
    assert [task.name for task in suite.tasks] == ["gsm8k", "review"]
    assert gsm8k.model == review.model == "gpt-4"
    # `generation` is merged section by section rather than replaced wholesale.
    assert (gsm8k.generation.max_tokens, gsm8k.generation.n) == (512, 5)
    assert (review.generation.scheme, review.generation.max_tokens) == ("greedy", 512)


def test_task_selection_keeps_only_the_named_tasks(tmp_path):
    suite = load_multi(tmp_path, selected=["review"])
    assert [task.name for task in suite.tasks] == ["review"]


def test_unknown_selected_task_is_reported(tmp_path):
    with pytest.raises(UsageError, match="unknown task 'humaneval'"):
        load_multi(tmp_path, selected=["humaneval"])


def test_judge_model_defaults_to_the_task_model(tmp_path):
    review = load_multi(tmp_path, selected=["review"]).tasks[0]
    assert review.evaluation.model == "gpt-4"


def test_eval_model_override_only_touches_llm_judge_tasks(tmp_path):
    suite = load_multi(tmp_path, {"eval_model": "judge-9"})
    gsm8k, review = suite.tasks

    assert review.evaluation.model == "judge-9"
    assert gsm8k.evaluation.model == "gpt-4"
    assert gsm8k.model == review.model == "gpt-4"


def test_missing_inherited_key_names_the_task(tmp_path):
    document = {**MULTI, "defaults": {"api_url": "http://localhost:8000"}}
    with pytest.raises(UsageError, match="tasks.gsm8k.model is required"):
        load_multi(tmp_path, document=document)


def test_llm_judge_requires_a_threshold(tmp_path):
    document = deepcopy(MULTI)
    del document["tasks"]["review"]["evaluation"]["threshold"]
    with pytest.raises(UsageError, match="tasks.review.evaluation.threshold is required"):
        load_multi(tmp_path, document=document)


def test_script_evaluation_requires_a_command_template(tmp_path):
    document = deepcopy(MULTI)
    document["tasks"]["review"]["evaluation"] = {"type": "script"}
    with pytest.raises(UsageError, match="tasks.review.evaluation.command_template is required"):
        load_multi(tmp_path, document=document)


def test_a_config_without_task_or_tasks_is_reported(tmp_path):
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump({"prompts": {}}))
    with pytest.raises(UsageError, match="expected a top level 'task' or 'tasks' mapping"):
        load_config(path, {})

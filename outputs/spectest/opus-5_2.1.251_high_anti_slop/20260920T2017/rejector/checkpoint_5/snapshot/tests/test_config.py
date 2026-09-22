"""Validation rules for the YAML task configuration."""

import pytest
import yaml

from config import load_config, overrides_from_flags
from errors import ConfigError

BASE = {
    "task": {
        "name": "t",
        "api_url": "http://localhost:8000",
        "model": "gpt-4",
        "rpm": 60,
        "prompt": {"system": "s", "user": "{question}"},
        "generation": {"scheme": "greedy", "max_tokens": 256},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    }
}


def load_task(path, overrides=None):
    """The one task of a single-task config."""
    return load_config(path, overrides).tasks[0]


def write_config(tmp_path, **task_changes):
    task = {**BASE["task"], **task_changes}
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return str(path)


def test_loads_full_config(tmp_path):
    config = load_task(write_config(tmp_path))
    assert config.model == "gpt-4"
    assert config.generation.max_tokens == 256
    assert config.evaluation.extract == "last_number"


def test_greedy_forces_zero_temperature(tmp_path):
    path = write_config(tmp_path, generation={"scheme": "greedy", "temperature": 0.9, "n": 4})
    config = load_task(path)
    assert config.generation.temperature == 0.0
    assert config.generation.n == 1


def test_sample_requires_positive_temperature(tmp_path):
    path = write_config(tmp_path, generation={"scheme": "sample", "temperature": 0.0})
    with pytest.raises(ConfigError, match="temperature must be > 0"):
        load_config(path)


def test_rejection_requires_something_to_reject_on(tmp_path):
    task = {**BASE["task"], "generation": {"scheme": "rejection", "temperature": 0.7, "n": 3}}
    del task["evaluation"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    with pytest.raises(ConfigError, match="needs an 'evaluation' or an 'output_schema'"):
        load_config(str(path))


def test_evaluation_optional_for_greedy(tmp_path):
    task = {**BASE["task"]}
    del task["evaluation"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    assert load_task(str(path)).evaluation is None


def test_contains_requires_answer_field(tmp_path):
    path = write_config(tmp_path, evaluation={"type": "contains"})
    with pytest.raises(ConfigError, match="answer_field is required"):
        load_config(path)


def test_regex_requires_pattern_but_not_answer_field(tmp_path):
    config = load_task(write_config(tmp_path, evaluation={"type": "regex", "pattern": r"\d+"}))
    assert config.evaluation.answer_field is None

    with pytest.raises(ConfigError, match="pattern is required"):
        load_config(write_config(tmp_path, evaluation={"type": "regex"}))


def test_rejects_unknown_scheme_and_extract(tmp_path):
    with pytest.raises(ConfigError, match="scheme must be one of"):
        load_config(write_config(tmp_path, generation={"scheme": "beam"}))
    with pytest.raises(ConfigError, match="extract must be one of"):
        load_config(write_config(tmp_path, evaluation={"type": "exact_match", "answer_field": "a", "extract": "first"}))


def test_missing_required_key(tmp_path):
    task = {**BASE["task"]}
    del task["output_field"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    with pytest.raises(ConfigError, match="task.output_field is required"):
        load_config(str(path))


def test_overrides_replace_config_values(tmp_path):
    flags = {"model": "other", "rpm": 200, "scheme": "sample", "temperature": 0.7, "n": 5}
    config = load_task(write_config(tmp_path), overrides_from_flags(flags))
    assert (config.model, config.rate_limits.rpm) == ("other", 200)
    assert (config.generation.scheme, config.generation.temperature) == ("sample", 0.7)
    assert config.generation.n == 1, "n only applies to rejection sampling"


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read config"):
        load_config(str(tmp_path / "nope.yaml"))


def test_rate_limits_default_to_the_task_level_rpm(tmp_path):
    limits = load_task(write_config(tmp_path)).rate_limits
    assert (limits.rpm, limits.tpm, limits.max_concurrent) == (60, None, None)


def test_rate_limits_are_read_from_their_own_section(tmp_path):
    task = write_config(tmp_path, rate_limits={"rpm": 100, "tpm": 50_000, "max_concurrent": 10})
    limits = load_task(task).rate_limits
    assert (limits.rpm, limits.tpm, limits.max_concurrent) == (100, 50_000, 10)


def test_a_task_may_configure_no_request_budget(tmp_path):
    task = {**BASE["task"], "rate_limits": {"tpm": 1000}}
    del task["rpm"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    assert load_task(str(path)).rate_limits.rpm is None


@pytest.mark.parametrize("key", ["rpm", "tpm", "max_concurrent"])
def test_a_budget_must_be_positive(tmp_path, key):
    path = write_config(tmp_path, rate_limits={key: 0})
    with pytest.raises(ConfigError, match=f"rate_limits.{key} must be > 0"):
        load_config(path)


def test_cost_is_read_with_zero_rates_by_default(tmp_path):
    cost = load_task(write_config(tmp_path, cost={"budget": 50})).cost
    assert (cost.prompt_cost_per_1k, cost.completion_cost_per_1k, cost.budget) == (0.0, 0.0, 50.0)


def test_a_task_without_a_cost_block_tracks_no_cost(tmp_path):
    assert load_task(write_config(tmp_path)).cost is None


def test_a_budget_of_zero_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="cost.budget must be > 0"):
        load_config(write_config(tmp_path, cost={"budget": 0}))


def test_the_new_flags_override_their_sections(tmp_path):
    flags = {"tpm": 30_000, "max_concurrent": 4, "budget": 2.5}
    config = load_task(write_config(tmp_path), overrides_from_flags(flags))
    assert (config.rate_limits.rpm, config.rate_limits.tpm) == (60, 30_000)
    assert config.rate_limits.max_concurrent == 4
    assert config.cost.budget == 2.5


def test_an_output_schema_is_kept_as_written(tmp_path):
    schema = {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}}
    assert load_task(write_config(tmp_path, output_schema=schema)).output_schema == schema


def test_an_output_schema_must_be_a_mapping(tmp_path):
    with pytest.raises(ConfigError, match="output_schema must be of type dict"):
        load_config(write_config(tmp_path, output_schema=["code"]))


def test_an_output_schema_can_stand_in_for_a_rejection_evaluation(tmp_path):
    task = {
        **BASE["task"],
        "generation": {"scheme": "rejection", "temperature": 0.7, "n": 3},
        "output_schema": {"type": "object"},
    }
    del task["evaluation"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    assert load_task(str(path)).evaluation is None

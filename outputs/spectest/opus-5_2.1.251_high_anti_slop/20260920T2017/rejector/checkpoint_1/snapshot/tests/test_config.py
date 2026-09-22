"""Validation rules for the YAML task configuration."""

import pytest
import yaml

from config import load_config
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


def write_config(tmp_path, **task_changes):
    task = {**BASE["task"], **task_changes}
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return str(path)


def test_loads_full_config(tmp_path):
    config = load_config(write_config(tmp_path))
    assert config.model == "gpt-4"
    assert config.generation.max_tokens == 256
    assert config.evaluation.extract == "last_number"


def test_greedy_forces_zero_temperature(tmp_path):
    path = write_config(tmp_path, generation={"scheme": "greedy", "temperature": 0.9, "n": 4})
    config = load_config(path)
    assert config.generation.temperature == 0.0
    assert config.generation.n == 1


def test_sample_requires_positive_temperature(tmp_path):
    path = write_config(tmp_path, generation={"scheme": "sample", "temperature": 0.0})
    with pytest.raises(ConfigError, match="temperature must be > 0"):
        load_config(path)


def test_rejection_requires_evaluation(tmp_path):
    task = {**BASE["task"], "generation": {"scheme": "rejection", "temperature": 0.7, "n": 3}}
    del task["evaluation"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    with pytest.raises(ConfigError, match="evaluation is required"):
        load_config(str(path))


def test_evaluation_optional_for_greedy(tmp_path):
    task = {**BASE["task"]}
    del task["evaluation"]
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    assert load_config(str(path)).evaluation is None


def test_contains_requires_answer_field(tmp_path):
    path = write_config(tmp_path, evaluation={"type": "contains"})
    with pytest.raises(ConfigError, match="answer_field is required"):
        load_config(path)


def test_regex_requires_pattern_but_not_answer_field(tmp_path):
    config = load_config(write_config(tmp_path, evaluation={"type": "regex", "pattern": r"\d+"}))
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
    overrides = {"model": "other", "rpm": 200, "scheme": "sample", "temperature": 0.7, "n": 5}
    config = load_config(write_config(tmp_path), overrides)
    assert (config.model, config.rpm) == ("other", 200)
    assert (config.generation.scheme, config.generation.temperature) == ("sample", 0.7)
    assert config.generation.n == 1, "n only applies to rejection sampling"


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read config"):
        load_config(str(tmp_path / "nope.yaml"))

"""Configuration loading and validation."""

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
    return load_config(write(tmp_path, **task), overrides or {})


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

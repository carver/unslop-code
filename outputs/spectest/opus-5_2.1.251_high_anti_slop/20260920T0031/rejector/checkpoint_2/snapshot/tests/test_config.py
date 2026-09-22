"""Configuration loading, defaults, overrides and validation."""

import pytest
import yaml

from config import load_tasks
from errors import RejectorError

BASE = {
    "task": {
        "name": "demo",
        "api_url": "http://localhost:8000/",
        "model": "gpt-4",
        "rpm": 30,
        "prompt": {"system": "sys", "user": "{question}"},
        "generation": {"scheme": "greedy", "temperature": 0.7, "max_tokens": 128},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
        "output_field": "solution",
    }
}

NO_OVERRIDES = dict.fromkeys(
    ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n", "eval_model")
)


def write_config(tmp_path, changes=None):
    """Write BASE with `changes` applied; a change of None drops that key entirely."""
    document = yaml.safe_load(yaml.safe_dump(BASE))
    for key, value in (changes or {}).items():
        if value is None:
            document["task"].pop(key)
        else:
            document["task"][key] = value
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump(document))
    return str(path)


def load(tmp_path, changes=None, **overrides):
    """The single task of a Part 1 style config."""
    return load_tasks(write_config(tmp_path, changes), {**NO_OVERRIDES, **overrides}).tasks[0]


def test_greedy_forces_temperature_to_zero(tmp_path):
    task = load(tmp_path)
    assert task.generation.temperature == 0.0
    assert task.generation.attempts == 1


def test_trailing_slash_stripped_from_api_url(tmp_path):
    assert load(tmp_path).api_url == "http://localhost:8000"


def test_cli_overrides_replace_config_values(tmp_path):
    task = load(tmp_path, scheme="rejection", temperature=0.4, n=5, model="mini", rpm=120, max_tokens=64)
    assert (task.model, task.rpm) == ("mini", 120)
    assert (task.generation.scheme, task.generation.temperature) == ("rejection", 0.4)
    assert (task.generation.n, task.generation.max_tokens) == (5, 64)
    assert task.generation.attempts == 5


def test_defaults_applied_for_absent_generation_fields(tmp_path):
    task = load(tmp_path, {"generation": {"scheme": "greedy"}, "rpm": None})
    assert (task.rpm, task.generation.max_tokens, task.generation.n) == (60, 512, 1)


def test_sample_requires_positive_temperature(tmp_path):
    with pytest.raises(RejectorError, match="temperature must be > 0"):
        load(tmp_path, scheme="sample", temperature=0.0)


def test_rejection_requires_evaluation(tmp_path):
    with pytest.raises(RejectorError, match="evaluation is required"):
        load(tmp_path, {"evaluation": None}, scheme="rejection", temperature=0.5)


def test_evaluation_optional_without_rejection(tmp_path):
    assert load(tmp_path, {"evaluation": None}).evaluation is None


def test_exact_match_requires_answer_field(tmp_path):
    with pytest.raises(RejectorError, match="answer_field is required"):
        load(tmp_path, {"evaluation": {"type": "exact_match", "extract": "full"}})


def test_regex_requires_pattern_but_no_answer_field(tmp_path):
    task = load(tmp_path, {"evaluation": {"type": "regex", "pattern": r"\d+"}})
    assert task.evaluation.pattern.search("answer 42")
    with pytest.raises(RejectorError, match="pattern is required"):
        load(tmp_path, {"evaluation": {"type": "regex"}})


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"evaluation": {"type": "bleu", "answer_field": "answer"}}, "evaluation.type"),
        ({"evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "first"}}, "extract"),
        ({"prompt": {"system": "sys"}}, "prompt.user"),
        ({"model": None}, "task.model"),
        ({"output_field": None}, "task.output_field"),
        ({"rpm": "many"}, "rpm must be a number"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path, changes, message):
    with pytest.raises(RejectorError, match=message):
        load(tmp_path, changes)


def test_unknown_scheme_is_rejected(tmp_path):
    with pytest.raises(RejectorError, match="generation.scheme"):
        load(tmp_path, {"generation": {"scheme": "beam"}})


def test_top_level_task_mapping_required(tmp_path):
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"job": {}}))
    with pytest.raises(RejectorError, match="'task' mapping"):
        load_tasks(str(path), NO_OVERRIDES)


def test_single_task_config_is_reported_as_such(tmp_path):
    suite = load_tasks(write_config(tmp_path), NO_OVERRIDES)
    assert (suite.multi, suite.names) == (False, ("demo",))

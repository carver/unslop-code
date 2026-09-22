"""Configuration loading, defaults, overrides and validation."""

import pytest
import yaml

from config import load_tasks
from errors import RejectorError
from rejector import OVERRIDE_FLAGS

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

NO_OVERRIDES = dict.fromkeys(OVERRIDE_FLAGS)


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
    assert (task.model, task.limits.rpm) == ("mini", 120)
    assert (task.generation.scheme, task.generation.temperature) == ("rejection", 0.4)
    assert (task.generation.n, task.generation.max_tokens) == (5, 64)
    assert task.generation.attempts == 5


def test_defaults_applied_for_absent_generation_fields(tmp_path):
    task = load(tmp_path, {"generation": {"scheme": "greedy"}, "rpm": None})
    assert (task.generation.max_tokens, task.generation.n) == (512, 1)
    # Without an rpm there is no request pacing, and the in-flight cap falls back.
    assert (task.limits.rpm, task.limits.tpm, task.limits.max_concurrent) == (None, None, 10)


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


def test_num_solutions_defaults_to_one_and_keeps_the_part_1_behaviour(tmp_path):
    task = load(tmp_path)
    assert (task.num_solutions, task.multi_solution) == (1, False)
    assert task.generation.max_attempts is None


def test_rejection_defaults_max_attempts_to_three_per_solution(tmp_path):
    task = load(tmp_path, {"num_solutions": 4}, scheme="rejection", temperature=0.5)
    assert (task.num_solutions, task.generation.max_attempts, task.multi_solution) == (4, 12, True)


def test_a_configured_max_attempts_wins(tmp_path):
    changes = {"num_solutions": 4, "generation": {"scheme": "rejection", "temperature": 0.5, "max_attempts": 15}}
    assert load(tmp_path, changes).generation.max_attempts == 15


def test_num_solutions_flag_overrides_the_config(tmp_path):
    task = load(tmp_path, {"num_solutions": 2}, num_solutions=6, scheme="rejection", temperature=0.5)
    assert (task.num_solutions, task.generation.max_attempts) == (6, 18)


@pytest.mark.parametrize("changes, message", [
    ({"num_solutions": 0}, "num_solutions must be >= 1"),
    ({"generation": {"scheme": "rejection", "temperature": 0.5, "max_attempts": 0}}, "max_attempts must be >= 1"),
])
def test_counts_must_be_positive(tmp_path, changes, message):
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

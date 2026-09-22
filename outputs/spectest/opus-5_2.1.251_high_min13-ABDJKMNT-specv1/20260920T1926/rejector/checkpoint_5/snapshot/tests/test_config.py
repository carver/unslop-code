"""Configuration parsing, defaults and the spec's validation rules."""

from __future__ import annotations

import pytest

from conftest import base_task
from fake_api import FakeAPI, always

from taskrunner.config import ConfigError, build_run_config


def build(task: dict, **overrides):
    """The single task of a Part 1 `task:` config."""
    return next(iter(build_run_config({"task": task}, overrides).tasks.values()))


# Spec: config shape "task: {name, api_url, model, rpm, prompt, generation,
# evaluation, output_field}".
# Context: Configuration.
def test_example_config_parses():
    config = build(base_task("http://localhost:8000"))
    assert config.name == "gsm8k_solve"
    assert config.api_url == "http://localhost:8000"
    assert config.model == "gpt-4"
    assert config.limits.rpm == 600
    assert config.output_field == "solution"
    assert config.prompt.user == "{question}"
    assert config.generation.scheme == "greedy"
    assert config.evaluation.type == "exact_match"


# Spec: "Optional overrides replace the corresponding config values when
# provided".
# Context: Deliverable.
def test_overrides_replace_config_values():
    config = build(
        base_task("http://localhost:8000"),
        api_url="http://other:9000",
        model="m2",
        rpm=42,
        max_tokens=7,
        scheme="sample",
        temperature=0.5,
        n=3,
    )
    assert (config.api_url, config.model, config.limits.rpm) == ("http://other:9000", "m2", 42)
    assert config.generation.max_tokens == 7
    assert config.generation.scheme == "sample"
    assert config.generation.temperature == 0.5
    assert config.generation.n == 3


def test_absent_overrides_do_not_replace_config_values():
    config = build(base_task("http://localhost:8000"), model=None, rpm=None)
    assert config.model == "gpt-4"
    assert config.limits.rpm == 600


# Spec: "greedy: force temperature to 0.0; n is ignored"
# Context: Configuration / generation behavior.
def test_greedy_forces_temperature_zero():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "greedy", "temperature": 0.9, "n": 5}
    config = build(task)
    assert config.generation.temperature == 0.0


# Spec: "sample: temperature must be > 0"
# Context: Configuration / generation behavior.
@pytest.mark.parametrize("temperature", [0.0, -0.5])
def test_sample_rejects_non_positive_temperature(temperature):
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "sample", "temperature": temperature}
    with pytest.raises(ConfigError):
        build(task)


def test_sample_accepts_positive_temperature():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "sample", "temperature": 0.7}
    assert build(task).generation.temperature == 0.7


# Spec: "rejection: temperature must be > 0; make up to n attempts"
# Context: Configuration / generation behavior.
def test_rejection_rejects_non_positive_temperature():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "rejection", "temperature": 0.0, "n": 3}
    with pytest.raises(ConfigError):
        build(task)


# Spec: "--scheme <greedy|sample|rejection>"
# Context: Deliverable; any other scheme is invalid configuration.
def test_unknown_scheme_is_rejected():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "beam"}
    with pytest.raises(ConfigError):
        build(task)


# Spec: "evaluation is required for rejection and optional otherwise"
# Context: Configuration / validation rules.
def test_rejection_requires_evaluation():
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "rejection", "temperature": 0.8, "n": 3}
    task.pop("evaluation")
    with pytest.raises(ConfigError):
        build(task)


@pytest.mark.parametrize("scheme", ["greedy", "sample"])
def test_evaluation_optional_for_greedy_and_sample(scheme):
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": scheme, "temperature": 0.0 if scheme == "greedy" else 0.7}
    task.pop("evaluation")
    assert build(task).evaluation is None


# Spec: "exact_match and contains require answer_field"
# Context: Configuration / validation rules.
@pytest.mark.parametrize("eval_type", ["exact_match", "contains"])
def test_answer_field_required(eval_type):
    task = base_task("http://localhost:8000")
    task["evaluation"] = {"type": eval_type}
    with pytest.raises(ConfigError):
        build(task)


# Spec: "regex requires pattern and does not require answer_field"
# Context: Configuration / validation rules.
def test_regex_requires_pattern():
    task = base_task("http://localhost:8000")
    task["evaluation"] = {"type": "regex"}
    with pytest.raises(ConfigError):
        build(task)


def test_regex_does_not_require_answer_field():
    task = base_task("http://localhost:8000")
    task["evaluation"] = {"type": "regex", "pattern": r"####\s*\d+"}
    config = build(task)
    assert config.evaluation.answer_field is None
    assert config.evaluation.pattern == r"####\s*\d+"


# Spec: "Evaluation types: exact_match, contains, regex"
# Context: Configuration; anything else is invalid.
def test_unknown_evaluation_type_is_rejected():
    task = base_task("http://localhost:8000")
    task["evaluation"] = {"type": "bleu", "answer_field": "answer"}
    with pytest.raises(ConfigError):
        build(task)


# Spec: "Extract methods: last_number, last_line, full"
# Context: Configuration; anything else is invalid.
def test_unknown_extract_method_is_rejected():
    task = base_task("http://localhost:8000")
    task["evaluation"] = {"type": "exact_match", "answer_field": "answer", "extract": "first"}
    with pytest.raises(ConfigError):
        build(task)


# Spec: defaults for keys the spec never marks required (see AMBIGUITIES T10).
# Context: Configuration shape.
def test_defaults_for_omitted_keys():
    task = {
        "api_url": "http://localhost:8000",
        "model": "gpt-4",
        "prompt": {"user": "{question}"},
        "output_field": "solution",
    }
    config = build(task)
    assert config.limits.rpm is None
    assert config.generation.scheme == "greedy"
    assert config.generation.max_tokens == 512
    assert config.generation.n == 1
    assert config.prompt.system is None


def test_extract_defaults_to_full():
    task = base_task("http://localhost:8000")
    task["evaluation"] = {"type": "exact_match", "answer_field": "answer"}
    assert build(task).evaluation.extract == "full"


# Spec: "Invalid configuration exits with code 1 and a descriptive message on
# stderr."
# Context: Configuration.
def test_invalid_config_exits_one_with_message(write_config, write_input, run_cli):
    task = base_task("http://localhost:8000")
    task["generation"] = {"scheme": "sample", "temperature": 0.0}
    config = write_config(task)
    data = write_input([{"question": "q", "answer": "5"}])
    result = run_cli(config, data)
    assert result.returncode == 1
    assert "temperature" in result.stderr.lower()


def test_missing_required_key_exits_one(write_config, write_input, run_cli):
    task = base_task("http://localhost:8000")
    task.pop("model")
    config = write_config(task)
    data = write_input([{"question": "q", "answer": "5"}])
    result = run_cli(config, data)
    assert result.returncode == 1
    assert "model" in result.stderr.lower()


def test_malformed_yaml_exits_one(write_input, run_cli, workdir):
    config = workdir / "broken.yaml"
    config.write_text("task: [unclosed\n")
    data = write_input([{"question": "q", "answer": "5"}])
    result = run_cli(config, data)
    assert result.returncode == 1


# Spec: "rejection: ... make up to n attempts" — validation happens before any
# API traffic.
# Context: Configuration / validation rules.
def test_invalid_config_makes_no_api_calls(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "rejection", "temperature": 0.8, "n": 3}
        task.pop("evaluation")
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 0
    assert result.returncode == 1

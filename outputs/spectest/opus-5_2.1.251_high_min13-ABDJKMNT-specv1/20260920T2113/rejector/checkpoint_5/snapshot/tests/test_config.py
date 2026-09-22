"""Config loading, CLI overrides, and the spec's validation rules."""

from __future__ import annotations

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import task_config


def load(cli, config, **overrides):
    return load_config(cli.write_config(config), overrides).only


# "Config shape: task: name / api_url / model / rpm / prompt / generation /
#  evaluation / output_field"
def test_spec_config_shape_loads(cli):
    config = load(cli, task_config(
        generation={"scheme": "greedy", "temperature": 0.0, "max_tokens": 512, "n": 1},
    ))
    assert config.name == "math_solve"
    assert config.api_url == "http://localhost:8000"
    assert config.model == "gpt-4"
    assert config.rpm == 60
    assert config.system_prompt == "Solve the math problem. Final answer after ####."
    assert config.user_prompt == "{question}"
    assert config.generation.scheme == "greedy"
    assert config.generation.max_tokens == 512
    assert config.generation.n == 1
    assert config.evaluation.type == "exact_match"
    assert config.evaluation.answer_field == "answer"
    assert config.evaluation.extract == "last_number"
    assert config.output_field == "solution"


# "--api-url / --model / --rpm / --max-tokens / --scheme / --temperature / --n:
#  Optional overrides replace the corresponding config values when provided"
def test_overrides_replace_config_values(cli):
    config = load(
        cli,
        task_config(),
        api_url="http://example.test:9000",
        model="gpt-5",
        rpm=120,
        max_tokens=64,
        scheme="sample",
        temperature=0.7,
        n=4,
    )
    assert (config.api_url, config.model, config.rpm) == ("http://example.test:9000", "gpt-5", 120)
    assert config.generation.scheme == "sample"
    assert config.generation.temperature == 0.7
    assert config.generation.max_tokens == 64
    assert config.generation.n == 4


# "Optional overrides replace the corresponding config values when provided"
# (absent overrides leave config values alone)
def test_absent_overrides_keep_config_values(cli):
    config = load(cli, task_config(), api_url=None, model=None, rpm=None)
    assert config.api_url == "http://localhost:8000"
    assert config.model == "gpt-4"
    assert config.rpm == 60


# "greedy: force temperature to 0.0; n is ignored"
def test_greedy_forces_temperature_to_zero(cli):
    config = load(cli, task_config(generation={"scheme": "greedy", "temperature": 0.9, "n": 7}))
    assert config.generation.temperature == 0.0


# "sample: temperature must be > 0"
def test_sample_requires_positive_temperature(cli):
    with pytest.raises(ConfigError, match="temperature"):
        load(cli, task_config(generation={"scheme": "sample", "temperature": 0.0}))


# "rejection: temperature must be > 0"
def test_rejection_requires_positive_temperature(cli):
    with pytest.raises(ConfigError, match="temperature"):
        load(cli, task_config(generation={"scheme": "rejection", "temperature": 0.0, "n": 3}))


# "sample: temperature must be > 0" (T11: absent temperature defaults to 0.0)
def test_sample_without_temperature_is_invalid(cli):
    with pytest.raises(ConfigError, match="temperature"):
        load(cli, task_config(generation={"scheme": "sample", "max_tokens": 32}))


# "--scheme <greedy|sample|rejection>"
def test_unknown_scheme_is_invalid(cli):
    with pytest.raises(ConfigError, match="scheme"):
        load(cli, task_config(generation={"scheme": "beam"}))


# "evaluation is required for rejection and optional otherwise"
def test_rejection_requires_evaluation(cli):
    config = task_config(generation={"scheme": "rejection", "temperature": 0.8, "n": 3})
    config["task"].pop("evaluation")
    with pytest.raises(ConfigError, match="evaluation"):
        load(cli, config)


# "evaluation is required for rejection and optional otherwise"
@pytest.mark.parametrize("scheme,temperature", [("greedy", 0.0), ("sample", 0.5)])
def test_evaluation_optional_for_greedy_and_sample(cli, scheme, temperature):
    config = task_config(generation={"scheme": scheme, "temperature": temperature})
    config["task"].pop("evaluation")
    assert load(cli, config).evaluation is None


# "exact_match and contains require answer_field"
@pytest.mark.parametrize("eval_type", ["exact_match", "contains"])
def test_answer_field_required(cli, eval_type):
    with pytest.raises(ConfigError, match="answer_field"):
        load(cli, task_config(evaluation={"type": eval_type, "extract": "full",
                                          "answer_field": None}))


# "regex requires pattern and does not require answer_field"
def test_regex_requires_pattern_but_not_answer_field(cli):
    with pytest.raises(ConfigError, match="pattern"):
        load(cli, task_config(evaluation={"type": "regex", "answer_field": None}))
    config = load(cli, task_config(evaluation={
        "type": "regex", "pattern": r"####\s*\d+", "answer_field": None,
    }))
    assert config.evaluation.pattern == r"####\s*\d+"
    assert config.evaluation.answer_field is None


# "evaluation: type: exact_match | contains | regex"
def test_unknown_evaluation_type_is_invalid(cli):
    with pytest.raises(ConfigError, match="type"):
        load(cli, task_config(evaluation={"type": "bleu", "answer_field": "answer"}))


# "extract: last_number | last_line | full" plus Part 2's "letter" / "first_number"
def test_unknown_extract_method_is_invalid(cli):
    with pytest.raises(ConfigError, match="extract"):
        load(cli, task_config(evaluation={"extract": "second_number"}))


# "Invalid configuration exits with code 1 and a descriptive message on stderr"
# (T7: extract defaults to full; T12: generation/system default. Part 5 replaced
#  T12's rpm default: "if rpm is omitted, RPM limiting is disabled for that task")
def test_optional_keys_default(cli):
    config = task_config(evaluation={"type": "exact_match", "answer_field": "answer"})
    del config["task"]["evaluation"]["extract"]
    del config["task"]["rpm"]
    del config["task"]["generation"]
    del config["task"]["prompt"]["system"]
    loaded = load(cli, config)
    assert loaded.evaluation.extract == "full"
    assert loaded.rpm is None
    assert loaded.generation.scheme == "greedy"
    assert loaded.generation.max_tokens == 512
    assert loaded.generation.n == 1
    assert loaded.system_prompt is None


# "Invalid configuration exits with code 1 and a descriptive message on stderr"
# (T12: required keys)
@pytest.mark.parametrize("missing", ["api_url", "model", "output_field"])
def test_required_keys_are_required(cli, missing):
    config = task_config()
    config["task"].pop(missing)
    with pytest.raises(ConfigError, match=missing):
        load(cli, config)


# "Invalid configuration exits with code 1 and a descriptive message on stderr"
def test_missing_user_prompt_is_invalid(cli):
    with pytest.raises(ConfigError, match="user"):
        load(cli, task_config(prompt={"system": "hi", "user": None}))


# "Invalid configuration exits with code 1 and a descriptive message on stderr"
def test_missing_task_section_is_invalid(cli):
    with pytest.raises(ConfigError, match="task"):
        load(cli, {"job": {}})


# "Invalid configuration exits with code 1 and a descriptive message on stderr"
def test_unparseable_yaml_is_invalid(cli):
    with pytest.raises(ConfigError):
        load_config(cli.write_config("task: [unclosed\n"), {})


# "Invalid configuration exits with code 1 and a descriptive message on stderr"
def test_missing_config_file_is_invalid(cli):
    with pytest.raises(ConfigError):
        load_config(cli.tmp_path / "nope.yaml", {})


# "rpm: 60" / "max_tokens: 512" / "n: 1" must be usable positive numbers
@pytest.mark.parametrize("key,value", [("rpm", 0), ("rpm", -1)])
def test_rpm_must_be_positive(cli, key, value):
    with pytest.raises(ConfigError, match="rpm"):
        load(cli, task_config(**{key: value}))


@pytest.mark.parametrize("field,value", [("max_tokens", 0), ("n", 0)])
def test_generation_numbers_must_be_positive(cli, field, value):
    with pytest.raises(ConfigError, match=field):
        load(cli, task_config(generation={"scheme": "greedy", field: value}))


# "regex requires pattern" (an uncompilable pattern is not usable)
def test_invalid_regex_pattern_is_invalid(cli):
    with pytest.raises(ConfigError, match="pattern"):
        load(cli, task_config(evaluation={"type": "regex", "pattern": "([unclosed"}))

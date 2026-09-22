"""Config shape, generation-scheme rules, and validation rules."""

from __future__ import annotations

import pytest

from conftest import make_config

ROW = [{"question": "What is 2 + 3?", "answer": "42"}]


# Spec: "Invalid configuration exits with code 1 and a descriptive message on
# stderr" -- YAML that does not parse.
def test_unparseable_yaml_exits_1(run_cli):
    result = run_cli("task: [unclosed\n", ROW)
    assert result.exit_code == 1
    assert result.stderr.strip()


# Spec: config shape is rooted at a `task:` mapping.
def test_missing_task_key_exits_1(run_cli):
    result = run_cli({"job": {"name": "x"}}, ROW)
    assert result.exit_code == 1
    assert "task" in result.stderr


# Spec: "generation: scheme: <greedy|sample|rejection>" -- anything else is
# invalid configuration.
def test_unknown_scheme_exits_1(server, run_cli):
    config = make_config(server.url, generation={"scheme": "beam", "temperature": 0.5})
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "beam" in result.stderr


# Spec: "greedy: force temperature to 0.0" -- even when the config asks for more.
def test_greedy_forces_temperature_zero(server, run_cli):
    config = make_config(server.url, generation={"scheme": "greedy", "temperature": 0.9})
    result = run_cli(config, ROW)
    assert result.exit_code == 0
    assert server.payloads[0]["temperature"] == 0.0


# Spec: "greedy: ... n is ignored" -- n>1 does not produce extra attempts.
def test_greedy_ignores_n(server, run_cli):
    config = make_config(
        server.url, generation={"scheme": "greedy", "n": 5}, evaluation=None
    )
    result = run_cli(config, [{"question": "q"}])
    assert server.call_count == 1
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "sample: temperature must be > 0".
def test_sample_with_zero_temperature_exits_1(server, run_cli):
    config = make_config(server.url, generation={"scheme": "sample", "temperature": 0.0})
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "temperature" in result.stderr


# Spec: "sample: temperature must be > 0" -- a positive temperature is sent
# through to the API unchanged.
def test_sample_sends_configured_temperature(server, run_cli):
    config = make_config(server.url, generation={"scheme": "sample", "temperature": 0.8})
    result = run_cli(config, ROW)
    assert result.exit_code == 0
    assert server.payloads[0]["temperature"] == 0.8


# Spec: "sample: ... n is ignored".
def test_sample_ignores_n(server, run_cli):
    config = make_config(
        server.url, generation={"scheme": "sample", "temperature": 0.8, "n": 4}
    )
    result = run_cli(config, ROW)
    assert server.call_count == 1
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "rejection: temperature must be > 0".
def test_rejection_with_zero_temperature_exits_1(server, run_cli):
    config = make_config(
        server.url, generation={"scheme": "rejection", "temperature": 0.0, "n": 3}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "temperature" in result.stderr


# Spec: "sample/rejection: temperature must be > 0" -- an omitted temperature
# has no value to satisfy the rule. (T6)
@pytest.mark.parametrize("scheme", ["sample", "rejection"])
def test_missing_temperature_exits_1(server, run_cli, scheme):
    config = make_config(server.url, generation={"scheme": scheme, "n": 2})
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "temperature" in result.stderr


# Spec: "evaluation is required for rejection".
def test_rejection_without_evaluation_exits_1(server, run_cli):
    config = make_config(
        server.url,
        generation={"scheme": "rejection", "temperature": 0.7, "n": 3},
        evaluation=None,
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "evaluation" in result.stderr


# Spec: "evaluation is ... optional otherwise" -- greedy runs without it.
def test_greedy_without_evaluation_is_valid(server, run_cli):
    config = make_config(server.url, evaluation=None)
    result = run_cli(config, [{"question": "q"}])
    assert result.exit_code == 0


# Spec: "if evaluation is omitted for greedy or sample, result.passed must be null".
@pytest.mark.parametrize(
    "generation",
    [{"scheme": "greedy"}, {"scheme": "sample", "temperature": 0.7}],
)
def test_passed_is_null_without_evaluation(server, run_cli, generation):
    config = make_config(server.url, generation=generation, evaluation=None)
    result = run_cli(config, [{"question": "q"}])
    assert result.rows[0]["result"]["passed"] is None


# Spec: "exact_match and contains require answer_field".
@pytest.mark.parametrize("eval_type", ["exact_match", "contains"])
def test_missing_answer_field_in_config_exits_1(server, run_cli, eval_type):
    config = make_config(server.url, evaluation={"type": eval_type, "extract": "full"})
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "answer_field" in result.stderr


# Spec: "regex requires pattern".
def test_regex_without_pattern_exits_1(server, run_cli):
    config = make_config(server.url, evaluation={"type": "regex"})
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "pattern" in result.stderr


# Spec: "regex ... does not require answer_field".
def test_regex_without_answer_field_is_valid(server, run_cli):
    config = make_config(server.url, evaluation={"type": "regex", "pattern": r"####"})
    result = run_cli(config, [{"question": "q"}])
    assert result.exit_code == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: "evaluation: type: exact_match|contains|regex" -- other types invalid.
def test_unknown_evaluation_type_exits_1(server, run_cli):
    config = make_config(
        server.url, evaluation={"type": "bleu", "answer_field": "answer"}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "bleu" in result.stderr


# Spec: "Extract methods: last_number, last_line, full" -- others invalid.
def test_unknown_extract_method_exits_1(server, run_cli):
    config = make_config(
        server.url,
        evaluation={"type": "exact_match", "answer_field": "answer", "extract": "first_word"},
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "first_word" in result.stderr


# Spec: config shape carries `output_field`, which names the single output key.
# (T15: required, since the output key has no default name.)
def test_missing_output_field_exits_1(server, run_cli):
    config = make_config(server.url)
    del config["task"]["output_field"]
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert "output_field" in result.stderr


# Spec: "api_url" and "model" are part of the task config and have no default.
@pytest.mark.parametrize("key", ["api_url", "model"])
def test_missing_api_url_or_model_exits_1(server, run_cli, key):
    config = make_config(server.url)
    del config["task"][key]
    result = run_cli(config, ROW)
    assert result.exit_code == 1
    assert key in result.stderr


# Spec: the greedy example omits `temperature` and `n` entirely, so generation
# defaults must cover them. (T15)
def test_greedy_example_config_without_temperature_or_n(server, run_cli):
    config = make_config(
        server.url, generation={"scheme": "greedy", "max_tokens": 256}
    )
    result = run_cli(config, ROW)
    assert result.exit_code == 0
    assert server.payloads[0]["temperature"] == 0.0
    assert server.payloads[0]["max_tokens"] == 256


# Spec: "max_tokens: 512" in the documented config shape is the default. (T15)
def test_max_tokens_defaults_to_512(server, run_cli):
    config = make_config(server.url, generation={"scheme": "greedy"})
    run_cli(config, ROW)
    assert server.payloads[0]["max_tokens"] == 512

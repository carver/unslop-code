"""Configuration parsing, generation-scheme rules, and validation errors."""

from __future__ import annotations

import pytest
from fake_server import FakeAPIServer, always
from conftest import base_config


def _rows(write_input):
    return write_input([{"question": "What is 2 + 3?", "answer": "5"}])


# Spec: "prompt.system and prompt.user use {field} placeholders resolved from
# each input row" - both messages are sent in order with the config's model
def test_request_body_matches_the_api_contract(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        run_cli(config, _rows(write_input))
        payloads = api.payloads
    assert payloads[0] == {
        "model": "gpt-4",
        "messages": [
            {"role": "system", "content": "Solve the math problem. Put your final answer after ####."},
            {"role": "user", "content": "What is 2 + 3?"},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }


# Spec: "greedy: force temperature to 0.0"
def test_greedy_forces_temperature_to_zero(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"]["temperature"] = 0.9
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        run_cli(config, _rows(write_input))
        payloads = api.payloads
    assert payloads[0]["temperature"] == 0.0


# Spec: "greedy: ... n is ignored"
def test_greedy_ignores_n(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"]["n"] = 5
    with FakeAPIServer(always("#### 9")) as api:  # never passes evaluation
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, _rows(write_input))
        call_count = len(api.requests)
    assert call_count == 1
    assert result.rows[0]["result"]["attempts"] == 1
    assert "n" not in api.payloads[0]


# Spec: "sample: temperature must be > 0; n is ignored"
def test_sample_sends_configured_temperature_and_ignores_n(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64, "n": 4}
    with FakeAPIServer(always("#### 9")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, _rows(write_input))
        payloads = api.payloads
    assert len(payloads) == 1
    assert payloads[0]["temperature"] == 0.7
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "sample: temperature must be > 0" - zero is invalid
def test_sample_with_zero_temperature_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["generation"] = {"scheme": "sample", "temperature": 0.0}
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "temperature" in result.stderr.lower()


# Spec: "rejection: temperature must be > 0"
def test_rejection_with_zero_temperature_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.0, "n": 3}
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "temperature" in result.stderr.lower()


# Spec: "evaluation is required for rejection"
def test_rejection_without_evaluation_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3}
    del config_map["task"]["evaluation"]
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "evaluation" in result.stderr.lower()


# Spec: "evaluation is ... optional otherwise" (greedy)
def test_greedy_without_evaluation_is_valid(write_config, write_input, run_cli):
    config_map = base_config("")
    del config_map["task"]["evaluation"]
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, _rows(write_input))
    assert result.returncode == 0


# Spec: "evaluation is ... optional otherwise" (sample)
def test_sample_without_evaluation_is_valid(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {"scheme": "sample", "temperature": 0.5}
    del config_map["task"]["evaluation"]
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, _rows(write_input))
    assert result.returncode == 0


# Spec: "exact_match and contains require answer_field"
@pytest.mark.parametrize("eval_type", ["exact_match", "contains"])
def test_missing_answer_field_exits_1(eval_type, write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["evaluation"] = {"type": eval_type}
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "answer_field" in result.stderr


# Spec: "regex requires pattern"
def test_regex_without_pattern_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["evaluation"] = {"type": "regex"}
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "pattern" in result.stderr


# Spec: "regex ... does not require answer_field"
def test_regex_without_answer_field_is_valid(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["evaluation"] = {"type": "regex", "pattern": r"####\s*\d+"}
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q"}]))
    assert result.returncode == 0
    assert result.rows[0]["result"]["passed"] is True


# Spec: "Invalid configuration exits with code 1 and a descriptive message on
# stderr" - unknown scheme
def test_unknown_scheme_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["generation"]["scheme"] = "beam"
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "beam" in result.stderr


# Spec: "Invalid configuration ..." - unknown evaluation type
def test_unknown_evaluation_type_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["evaluation"] = {"type": "bleu", "answer_field": "answer"}
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "bleu" in result.stderr


# Spec: "Invalid configuration ..." - unknown extract method.  Part 2 added
# `letter` and `first_number`, so the rejected name must be outside both parts.
def test_unknown_extract_method_exits_1(write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    config_map["task"]["evaluation"]["extract"] = "middle_number"
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "middle_number" in result.stderr


# Spec: "Invalid configuration ..." - required task keys must be present
@pytest.mark.parametrize("missing", ["api_url", "model", "prompt", "output_field"])
def test_missing_required_task_key_exits_1(missing, write_config, write_input, run_cli):
    config_map = base_config("http://127.0.0.1:1")
    del config_map["task"][missing]
    config = write_config(config_map)
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert missing in result.stderr


# Spec: "Invalid configuration ..." - the file must hold a task mapping
def test_config_without_task_section_exits_1(write_config, write_input, run_cli):
    config = write_config({"job": {"model": "gpt-4"}})
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "task" in result.stderr


# Spec: "Invalid configuration ..." - unparsable YAML
def test_malformed_yaml_exits_1(workdir, write_input, run_cli):
    config = workdir / "task.yaml"
    config.write_text("task: [unclosed\n")
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert result.stderr.strip()

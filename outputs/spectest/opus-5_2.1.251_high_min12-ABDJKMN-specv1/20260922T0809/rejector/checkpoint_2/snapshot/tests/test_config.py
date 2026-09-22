"""Spec section: Configuration (config shape, defaults, validation rules)."""
from __future__ import annotations

import pytest

from conftest import base_config
from mock_server import MockAPI, always


# ---------------------------------------------------------------------------
# Phrase: the `Config shape:` YAML block (task.name/api_url/model/rpm/prompt/
#         generation/evaluation/output_field)
# Context: Configuration.  The canonical config from the spec must load and run.
# ---------------------------------------------------------------------------
def test_canonical_config_shape_is_accepted(run_tool, write_config, write_input):
    with MockAPI(always("5 + 3 = 8\n#### 8")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "5 apples + 3?", "answer": "8"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "Invalid configuration exits with code 1 and a descriptive message on
#          stderr."
# Context: Configuration.  A config with no `task` key at all.
# ---------------------------------------------------------------------------
def test_config_without_task_key_exits_1(run_tool, write_config, write_input):
    cfg = write_config({"name": "oops"})
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a config with no prompt block.
def test_config_without_prompt_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1", prompt=None))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a config with no api_url and no --api-url override.
def test_config_without_api_url_exits_1(run_tool, write_config, write_input):
    cfg_dict = base_config("http://x")
    del cfg_dict["task"]["api_url"]
    cfg = write_config(cfg_dict)
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a config with no model.
def test_config_without_model_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1", model=None))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - an unknown generation scheme.
def test_unknown_scheme_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1",
                                   generation={"scheme": "beam"}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - an unknown evaluation type.
def test_unknown_evaluation_type_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1",
                                   evaluation={"type": "bleu"}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - an unknown extract method.  (`first_number` became a
# valid method in Part 2, so this uses a name neither part defines.)
def test_unknown_extract_method_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config("http://127.0.0.1:1",
                                   evaluation={"extract": "second_number"}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "sample: temperature must be > 0"
# Context: Configuration / Generation behavior.  Validation rule.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("temperature", [0.0, -0.5])
def test_sample_requires_positive_temperature(run_tool, write_config,
                                              write_input, temperature):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        generation={"scheme": "sample", "temperature": temperature}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "rejection: temperature must be > 0"
# Context: Configuration / Generation behavior.
# ---------------------------------------------------------------------------
def test_rejection_requires_positive_temperature(run_tool, write_config,
                                                 write_input):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        generation={"scheme": "rejection", "temperature": 0.0, "n": 3}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - a positive temperature via --temperature repairs an
# otherwise invalid sample config, because overrides replace config values.
def test_temperature_override_satisfies_sample_validation(run_tool,
                                                          write_config,
                                                          write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url, generation={"scheme": "sample", "temperature": 0.0}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--temperature", "0.9"])
    assert res.returncode == 0, res


# ---------------------------------------------------------------------------
# Phrase: "evaluation is required for rejection and optional otherwise"
# Context: Configuration / Validation rules.
# ---------------------------------------------------------------------------
def test_rejection_without_evaluation_exits_1(run_tool, write_config,
                                              write_input):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        generation={"scheme": "rejection", "temperature": 0.7, "n": 3},
        evaluation=None))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# Context: same phrase - evaluation is optional for greedy.
def test_greedy_without_evaluation_is_valid(run_tool, write_config, write_input):
    with MockAPI(always("some answer")) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res


# Context: same phrase - evaluation is optional for sample.
def test_sample_without_evaluation_is_valid(run_tool, write_config, write_input):
    with MockAPI(always("some answer")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "sample", "temperature": 0.5},
            evaluation=None))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res


# ---------------------------------------------------------------------------
# Phrase: "exact_match and contains require answer_field"
# Context: Configuration / Validation rules.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("etype", ["exact_match", "contains"])
def test_evaluation_requires_answer_field(run_tool, write_config, write_input,
                                          etype):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        evaluation={"type": etype, "answer_field": None, "extract": "full"}))
    data = write_input([{"question": "q", "answer": "5"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "regex requires pattern and does not require answer_field"
# Context: Configuration / Validation rules.
# ---------------------------------------------------------------------------
def test_regex_without_pattern_exits_1(run_tool, write_config, write_input):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        evaluation={"type": "regex", "answer_field": None, "extract": None}))
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


def test_regex_without_answer_field_is_valid(run_tool, write_config,
                                             write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url,
            evaluation={"type": "regex", "pattern": r"####\s*\d+",
                        "answer_field": None, "extract": None}))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "if evaluation is omitted for greedy or sample, result.passed must be
#          null"
# Context: Configuration / Validation rules.
# ---------------------------------------------------------------------------
def test_passed_is_null_without_evaluation(run_tool, write_config, write_input):
    with MockAPI(always("free-form answer")) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": "q"}, {"question": "q2"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    for row in res.rows:
        assert row["result"]["passed"] is None
        assert row["result"]["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Phrase (ambiguity T11): fields present in the spec's *example* config are the
#         required set; `temperature` and `n` may be omitted for greedy.
# Context: Examples / Greedy example config omits temperature and n.
# ---------------------------------------------------------------------------
def test_greedy_example_config_without_temperature_or_n(run_tool, write_config,
                                                        write_input):
    with MockAPI(always("2 + 3 = 5\n#### 5")) as api:
        cfg = write_config({
            "task": {
                "name": "math_solve",
                "api_url": api.url,
                "model": "gpt-4",
                "rpm": 60,
                "prompt": {
                    "system": "Solve the math problem. Final answer after ####.",
                    "user": "{question}",
                },
                "generation": {"scheme": "greedy", "max_tokens": 256},
                "evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": "last_number"},
                "output_field": "solution",
            }
        })
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == 256
    assert res.rows[0] == {
        "input": {"question": "What is 2 + 3?", "answer": "5"},
        "output": {"solution": "2 + 3 = 5\n#### 5"},
        "result": {"passed": True, "extracted_answer": "5", "attempts": 1},
        "meta": res.rows[0]["meta"],
    }

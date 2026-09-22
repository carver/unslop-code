"""Multi-task config shape: `defaults`, per-task overrides, nested merging."""

from __future__ import annotations

import pytest

from conftest import exact_match_task, make_multi_config, make_config

ROWS = {"gsm8k": [{"question": "2+3?", "answer": "42"}]}


# Spec: "Multi-task configs use `defaults` plus a `tasks` mapping" -- a task
# that names none of the shared values still runs against them.
def test_defaults_supply_shared_values(server, run_multi):
    config = make_multi_config(server.url, {"gsm8k": exact_match_task()})
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["model"] == "gpt-4"
    assert result.rows("gsm8k")[0]["result"]["passed"] is True


# Spec: "`defaults` provides shared values; each task overrides `defaults`".
def test_task_overrides_a_default_scalar(server, run_multi):
    config = make_multi_config(
        server.url, {"gsm8k": exact_match_task(model="o3-mini")}
    )
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["model"] == "o3-mini"


# Spec: "nested sections such as `prompt`, `generation`, and `evaluation` are
# merged per task" -- `defaults.generation.max_tokens` survives a task that
# only sets the scheme and temperature.
def test_generation_section_is_merged(server, run_multi):
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(
                generation={"scheme": "sample", "temperature": 0.7}
            )
        },
        generation={"max_tokens": 128},
    )
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["max_tokens"] == 128
    assert server.payloads[0]["temperature"] == 0.7


# Spec: "nested sections such as `prompt` ... are merged per task" -- a shared
# system prompt plus a per-task user template.
def test_prompt_section_is_merged(server, run_multi):
    task = exact_match_task(prompt={"user": "{question}"})
    config = make_multi_config(
        server.url, {"gsm8k": task}, prompt={"system": "Shared system prompt."}
    )
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert server.payloads[0]["messages"] == [
        {"role": "system", "content": "Shared system prompt."},
        {"role": "user", "content": "2+3?"},
    ]


# Spec: "nested sections such as ... `evaluation` are merged per task".
def test_evaluation_section_is_merged(server, run_multi):
    task = exact_match_task(evaluation={"extract": "last_number"})
    config = make_multi_config(
        server.url,
        {"gsm8k": task},
        evaluation={"type": "exact_match", "answer_field": "answer"},
    )
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert result.rows("gsm8k")[0]["result"]["extracted_answer"] == "42"


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task" -- supplied only by the task.
def test_required_field_may_come_from_the_task(server, run_multi):
    config = make_multi_config(server.url, {"gsm8k": exact_match_task(model="gpt-4")})
    del config["defaults"]["model"]
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task" -- absent from both is a configuration error.
@pytest.mark.parametrize("key", ["api_url", "model"])
def test_required_field_missing_from_both_exits_1(server, run_multi, key):
    config = make_multi_config(server.url, {"gsm8k": exact_match_task()})
    del config["defaults"][key]
    result = run_multi(config, ROWS)
    assert result.exit_code == 1
    assert key in result.stderr


# Spec: "required Part 1 fields must still come from either `defaults` or the
# task" -- `output_field` names the per-task output key.
def test_missing_output_field_exits_1(server, run_multi):
    task = exact_match_task()
    del task["output_field"]
    config = make_multi_config(server.url, {"gsm8k": task})
    result = run_multi(config, ROWS)
    assert result.exit_code == 1
    assert "output_field" in result.stderr


# Spec: "Each task has its own ... output field".
def test_each_task_uses_its_own_output_field(server, run_multi):
    config = make_multi_config(
        server.url,
        {
            "gsm8k": exact_match_task(output_field="solution"),
            "mmlu": exact_match_task(output_field="choice"),
        },
    )
    result = run_multi(
        config, {"gsm8k": ROWS["gsm8k"], "mmlu": [{"question": "q", "answer": "42"}]}
    )
    assert result.exit_code == 0, result.stderr
    assert set(result.rows("gsm8k")[0]["output"]) == {"solution"}
    assert set(result.rows("mmlu")[0]["output"]) == {"choice"}


# Spec: "Each task has its own prompt, generation settings, evaluation" -- two
# tasks with different schemes in one run.
def test_tasks_keep_independent_generation_settings(servers, run_multi):
    server = servers(contents=["#### 1"], workers=1)
    config = make_multi_config(
        server.url,
        {
            "greedy_task": exact_match_task(),
            "rejection_task": exact_match_task(
                generation={"scheme": "rejection", "temperature": 0.7, "n": 3}
            ),
        },
    )
    rows = [{"question": "q", "answer": "42"}]
    result = run_multi(config, {"greedy_task": rows, "rejection_task": rows})
    assert result.rows("greedy_task")[0]["result"]["attempts"] == 1
    assert result.rows("rejection_task")[0]["result"]["attempts"] == 3


# Spec: "if the config still uses a top-level `task` key, treat it as the
# Part 1 single-task format" -- one input path, one output file.
def test_top_level_task_key_is_the_part_1_format(server, run_cli):
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "42"}])
    assert result.exit_code == 0
    assert len(result.rows) == 1


# Spec: "the task name is `task.name`" for a single-task config, so it is the
# key the summary reports the task under. (T20)
def test_single_task_name_comes_from_task_name(server, run_cli):
    config = make_config(server.url, name="math_solve")
    result = run_cli(config, [{"question": "q", "answer": "42"}])
    assert list(result.summary["tasks"]) == ["math_solve"]


# Spec: a config with neither a `task` mapping nor a `tasks` mapping cannot be
# used.
def test_config_without_task_or_tasks_exits_1(server, run_multi):
    result = run_multi({"defaults": {"api_url": server.url}}, ROWS)
    assert result.exit_code == 1
    assert "task" in result.stderr


# Spec: "each task overrides `defaults`" -- an evaluation that only exists in
# `defaults` still applies to a task that declares none.
def test_task_inherits_the_default_evaluation(server, run_multi):
    task = exact_match_task()
    del task["evaluation"]
    config = make_multi_config(
        server.url,
        {"gsm8k": task},
        evaluation={
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
    )
    result = run_multi(config, ROWS)
    assert result.exit_code == 0, result.stderr
    assert result.rows("gsm8k")[0]["result"]["passed"] is True

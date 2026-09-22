"""The `rate_limits`, `cost` and `output_schema` sections of a task."""

import pytest
import yaml
from test_config import NO_OVERRIDES, load, write_config
from test_multi_config import MULTI

from config import load_tasks
from errors import RejectorError

SCHEMA = {"type": "object", "required": ["code"], "properties": {"code": {"type": "string"}}}


def load_multi(tmp_path, document, **overrides):
    path = tmp_path / "multi.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return {task.name: task for task in load_tasks(str(path), {**NO_OVERRIDES, **overrides}).tasks}


def test_rate_limits_and_cost_are_read_from_the_task(tmp_path):
    task = load(tmp_path, {
        "rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10},
        "cost": {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03, "budget": 50.0},
    })
    assert (task.limits.rpm, task.limits.tpm, task.limits.max_concurrent) == (100, 50000, 10)
    assert (task.cost.prompt_per_1k, task.cost.completion_per_1k, task.cost.budget) == (0.01, 0.03, 50.0)


def test_max_concurrent_falls_back_to_a_minute_of_requests(tmp_path):
    assert load(tmp_path, {"rate_limits": {"rpm": 120}}).limits.max_concurrent == 120


def test_a_task_without_a_cost_section_is_uncosted(tmp_path):
    assert load(tmp_path).cost is None


def test_the_budget_flag_costs_an_otherwise_uncosted_task(tmp_path):
    assert load(tmp_path, budget=5.0).cost.budget == 5.0


def test_the_limit_flags_override_the_config(tmp_path):
    task = load(tmp_path, {"rate_limits": {"rpm": 100, "tpm": 1000}}, rpm=300, tpm=9000, max_concurrent=4)
    assert (task.limits.rpm, task.limits.tpm, task.limits.max_concurrent) == (300, 9000, 4)


def test_defaults_merge_into_every_task_key_by_key(tmp_path):
    document = {
        **MULTI,
        "defaults": {
            **MULTI["defaults"],
            "rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10},
            "cost": {"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03, "budget": 50.0},
        },
    }
    document["tasks"] = {
        **document["tasks"],
        "code_gen": {**document["tasks"]["code_gen"], "rate_limits": {"tpm": 30000},
                     "cost": {"prompt_cost_per_1k": 0.005}},
    }
    tasks = load_multi(tmp_path, document)

    assert (tasks["gsm8k"].limits.tpm, tasks["code_gen"].limits.tpm) == (50000, 30000)
    assert (tasks["gsm8k"].limits.rpm, tasks["code_gen"].limits.rpm) == (100, 100)
    assert tasks["code_gen"].cost.prompt_per_1k == 0.005
    assert (tasks["code_gen"].cost.completion_per_1k, tasks["code_gen"].cost.budget) == (0.03, 50.0)


def test_an_output_schema_is_kept_as_written(tmp_path):
    assert load(tmp_path, {"output_schema": SCHEMA}).output_schema == SCHEMA


def test_rejection_may_be_gated_by_a_schema_alone(tmp_path):
    task = load(tmp_path, {"evaluation": None, "output_schema": SCHEMA}, scheme="rejection", temperature=0.5)
    assert (task.evaluation, task.output_schema) == (None, SCHEMA)


def test_rejection_without_evaluation_or_schema_is_rejected(tmp_path):
    with pytest.raises(RejectorError, match="evaluation is required"):
        load(tmp_path, {"evaluation": None}, scheme="rejection", temperature=0.5)


@pytest.mark.parametrize("changes, message", [
    ({"rate_limits": {"tpm": 0}}, "tpm must be >= 1"),
    ({"rate_limits": {"max_concurrent": -1}}, "max_concurrent must be >= 1"),
    ({"cost": {"budget": "lots"}}, "budget must be a number"),
    ({"output_schema": ["code"]}, "output_schema must be a mapping"),
])
def test_invalid_sections_are_rejected(tmp_path, changes, message):
    with pytest.raises(RejectorError, match=message):
        load_tasks(write_config(tmp_path, changes), NO_OVERRIDES)

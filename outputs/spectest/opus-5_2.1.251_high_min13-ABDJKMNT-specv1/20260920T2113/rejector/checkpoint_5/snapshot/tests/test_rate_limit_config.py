"""The `rate_limits` config section, its merging, and its CLI overrides."""

from __future__ import annotations

import pytest

from rejlib.config import load_config
from rejlib.errors import ConfigError
from tests.conftest import multi_config, task_config


def load(cli, config, **overrides):
    return load_config(cli.write_config(config), overrides)


# "defaults:\n  rate_limits:\n    rpm: 100\n    tpm: 50000\n    max_concurrent: 10"
def test_rate_limits_section_loads(cli):
    config = multi_config(
        "gsm8k", defaults={"rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10}}
    )
    limits = load(cli, config).tasks["gsm8k"].rate_limits
    assert (limits.rpm, limits.tpm, limits.max_concurrent) == (100, 50000, 10)


# "For multi-task configs, `defaults.rate_limits` is merged into each task the
#  same way earlier checkpoints merged `prompt`, `generation`, and `evaluation`."
def test_defaults_rate_limits_reach_every_task(cli):
    config = multi_config(
        "gsm8k", "mmlu", defaults={"rate_limits": {"rpm": 100, "tpm": 50000}}
    )
    tasks = load(cli, config).tasks
    assert [task.rate_limits.tpm for task in tasks.values()] == [50000, 50000]
    assert [task.rate_limits.rpm for task in tasks.values()] == [100, 100]


# "Per-task `rate_limits` keys override only the keys they specify."
# "tasks:\n  code_gen:\n    rate_limits:\n      tpm: 30000"
def test_per_task_rate_limits_override_only_their_own_keys(cli):
    config = multi_config(
        "gsm8k", "code_gen",
        defaults={"rate_limits": {"rpm": 100, "tpm": 50000, "max_concurrent": 10}},
    )
    config["tasks"]["code_gen"]["rate_limits"] = {"tpm": 30000}
    tasks = load(cli, config).tasks
    assert tasks["code_gen"].rate_limits.tpm == 30000
    assert tasks["code_gen"].rate_limits.rpm == 100
    assert tasks["code_gen"].rate_limits.max_concurrent == 10
    assert tasks["gsm8k"].rate_limits.tpm == 50000


# "CLI flags: --tpm <int>"
def test_tpm_flag_overrides_config(cli):
    config = task_config(rate_limits={"tpm": 50000})
    assert load(cli, config, tpm=1234).only.rate_limits.tpm == 1234


# "CLI flags: --max-concurrent <int>"
def test_max_concurrent_flag_overrides_config(cli):
    config = task_config(rate_limits={"max_concurrent": 10})
    assert load(cli, config, max_concurrent=2).only.rate_limits.max_concurrent == 2


# "--rpm" keeps overriding the request budget, now wherever it is configured
def test_rpm_flag_overrides_rate_limits(cli):
    config = task_config(rate_limits={"rpm": 100})
    del config["task"]["rpm"]
    assert load(cli, config, rpm=7).only.rate_limits.rpm == 7


# "continue to enforce RPM" - the Part 1 top-level `rpm` still configures it
def test_top_level_rpm_still_configures_the_budget(cli):
    assert load(cli, task_config(rpm=45)).only.rate_limits.rpm == 45


# "if `rpm` is omitted, RPM limiting is disabled for that task"
def test_omitted_rpm_disables_request_limiting(cli):
    config = task_config()
    del config["task"]["rpm"]
    assert load(cli, config).only.rate_limits.rpm is None


# "if `rpm` is omitted, RPM limiting is disabled for that task" (per task: one
#  task may be paced while another is not)
def test_rpm_can_be_disabled_for_one_task_only(cli):
    config = multi_config("gsm8k", "mmlu", defaults={"rate_limits": {"tpm": 5000}})
    config["defaults"].pop("rpm")
    config["tasks"]["gsm8k"]["rate_limits"] = {"rpm": 100}
    tasks = load(cli, config).tasks
    assert tasks["gsm8k"].rate_limits.rpm == 100
    assert tasks["mmlu"].rate_limits.rpm is None


# "tpm: 50000" / "max_concurrent: 10" must be usable positive numbers
@pytest.mark.parametrize("key,value", [("tpm", 0), ("tpm", -1), ("max_concurrent", 0)])
def test_rate_limits_must_be_positive(cli, key, value):
    with pytest.raises(ConfigError, match=key):
        load(cli, task_config(rate_limits={key: value}))


# "when `tpm` is configured" - an absent tpm leaves token limiting off
def test_tpm_defaults_to_disabled(cli):
    assert load(cli, task_config()).only.rate_limits.tpm is None
    assert load(cli, task_config()).only.rate_limits.max_concurrent is None

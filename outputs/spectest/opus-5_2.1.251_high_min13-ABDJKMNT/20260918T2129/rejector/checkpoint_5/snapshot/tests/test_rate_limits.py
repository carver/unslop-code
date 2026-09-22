"""The `rate_limits` block: merging, CLI overrides, and enforcement."""

from __future__ import annotations

import time

import pytest
from fake_server import FakeAPIServer, Reply, completion, system_of, user_of
from conftest import GSM8K_TASK, MMLU_TASK, base_config, multi_config

from rejector_core.config import load_config


def _load(config_map, write_config, **overrides):
    """Build the single task of `config_map` with CLI overrides applied."""
    return load_config(write_config(config_map), overrides).tasks[0]


def _rows(write_input, count=1):
    return write_input([{"question": f"q{i}", "answer": "5"} for i in range(count)])


def _slow(delay=0.15):
    return lambda payload, index: Reply(completion("#### 5"), delay=delay)


# Spec: "defaults.rate_limits is merged into each task the same way earlier
# checkpoints merged prompt, generation, and evaluation"
def test_defaults_rate_limits_reach_every_task(write_config):
    config_map = multi_config("http://x", {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK})
    config_map["defaults"]["rate_limits"] = {"rpm": 100, "tpm": 50000, "max_concurrent": 10}
    tasks = load_config(write_config(config_map), {}).tasks

    assert [task.rate_limits.tpm for task in tasks] == [50000, 50000]
    assert [task.rate_limits.max_concurrent for task in tasks] == [10, 10]


# Spec: "Per-task `rate_limits` keys override only the keys they specify."
def test_per_task_rate_limits_override_only_their_own_keys(write_config):
    code_gen = dict(GSM8K_TASK, rate_limits={"tpm": 30000})
    config_map = multi_config("http://x", {"code_gen": code_gen, "mmlu": MMLU_TASK})
    config_map["defaults"]["rate_limits"] = {"rpm": 100, "tpm": 50000, "max_concurrent": 10}
    tasks = {task.name: task for task in load_config(write_config(config_map), {}).tasks}

    assert tasks["code_gen"].rate_limits.tpm == 30000
    assert tasks["code_gen"].rate_limits.rpm == 100
    assert tasks["code_gen"].rate_limits.max_concurrent == 10
    assert tasks["mmlu"].rate_limits.tpm == 50000


# Spec: CLI flag "--tpm <int>"
def test_tpm_flag_overrides_the_config(write_config):
    config_map = base_config("http://x", rate_limits={"tpm": 1000})
    assert _load(config_map, write_config, tpm=25).rate_limits.tpm == 25


# Spec: CLI flag "--max-concurrent <int>"
def test_max_concurrent_flag_overrides_the_config(write_config):
    config_map = base_config("http://x", rate_limits={"max_concurrent": 4})
    assert _load(config_map, write_config, max_concurrent=2).rate_limits.max_concurrent == 2


# Spec: "--rpm" now feeds the rate-limit block (T81)
def test_rpm_flag_overrides_the_rate_limit_block(write_config):
    config_map = base_config("http://x", rate_limits={"rpm": 100})
    assert _load(config_map, write_config, rpm=7).rate_limits.rpm == 7


# Spec: earlier checkpoints put `rpm` directly on the task; that spelling
# still configures the request window (T81)
def test_the_legacy_task_level_rpm_key_is_still_read(write_config):
    assert _load(base_config("http://x", rpm=42), write_config).rate_limits.rpm == 42


# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task" (T82)
def test_omitting_rpm_disables_request_limiting(write_config):
    config_map = base_config("http://x")
    config_map["task"].pop("rpm")
    assert _load(config_map, write_config).rate_limits.rpm is None


# Spec: "`rate_limits.rpm`" takes precedence over the Part 1 spelling (T81)
def test_rate_limits_rpm_wins_over_the_legacy_key(write_config):
    config_map = base_config("http://x", rpm=42, rate_limits={"rpm": 9})
    assert _load(config_map, write_config).rate_limits.rpm == 9


# Spec: "`max_concurrent` is a hard cap on in-flight requests independent of
# RPM and TPM"
@pytest.mark.slow
def test_max_concurrent_caps_requests_in_flight(write_config, write_input, run_cli):
    with FakeAPIServer(_slow(), capacity=64) as api:
        config_map = base_config(api.url, rpm=6000)
        config_map["task"]["rate_limits"] = {"max_concurrent": 3}
        config = write_config(config_map)
        run_cli(config, _rows(write_input, 12))
        peak = api.peak_in_flight

    assert peak <= 3


# Spec: "--max-concurrent <int>" - the flag caps in-flight requests too
@pytest.mark.slow
def test_max_concurrent_flag_caps_requests_in_flight(write_config, write_input, run_cli):
    with FakeAPIServer(_slow(), capacity=64) as api:
        config = write_config(base_config(api.url, rpm=6000))
        run_cli(config, _rows(write_input, 12), "--max-concurrent", "2")
        peak = api.peak_in_flight

    assert peak <= 2


# Spec: "reserve against `estimated_prompt_tokens + max_tokens` before
# dispatch" - a tpm that fits only one such reservation serialises the run
@pytest.mark.slow
def test_tpm_reservation_paces_dispatch(write_config, write_input, run_cli):
    with FakeAPIServer(_slow(0.05), capacity=64) as api:
        config_map = base_config(api.url, rpm=6000)
        config_map["task"]["generation"]["max_tokens"] = 64
        config_map["task"]["rate_limits"] = {"tpm": 100}
        config = write_config(config_map)
        started = time.monotonic()
        result = run_cli(config, _rows(write_input, 2))
        elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed >= 60


# Spec: "each `llm_judge` call goes through the same limiter"
@pytest.mark.slow
def test_judge_calls_hold_the_concurrency_budget(write_config, write_input, run_cli):
    def responder(payload, index):
        return Reply(completion("5" if "Score" in system_of(payload) else "#### 5"), delay=0.15)

    with FakeAPIServer(responder, capacity=64) as api:
        config_map = base_config(api.url, rpm=6000)
        config_map["task"]["rate_limits"] = {"max_concurrent": 2}
        config_map["task"]["evaluation"] = {
            "type": "llm_judge",
            "threshold": 4,
            "judge_prompt": {"system": "Score it", "user": "{question}"},
        }
        config = write_config(config_map)
        run_cli(config, _rows(write_input, 8))
        peak = api.peak_in_flight

    assert peak <= 2


# Spec: "for agentic loops, every API request counts toward RPM and TPM, and
# the loop holds one concurrency slot for its entire lifetime"
@pytest.mark.slow
def test_an_agentic_loop_never_exceeds_its_concurrency_slot(write_config, write_input, run_cli):
    from conftest import agentic_config
    from fake_server import conversation

    responder = conversation([[("lookup", {"key": "employees"})], "#### 142"])

    def delayed(payload, index):
        reply = responder(payload, index)
        return Reply(reply.body, delay=0.1)

    with FakeAPIServer(delayed, capacity=64) as api:
        config_map = agentic_config(api.url, rpm=6000)
        config_map["task"]["rate_limits"] = {"max_concurrent": 2}
        config = write_config(config_map)
        run_cli(config, _rows(write_input, 6))
        peak = api.peak_in_flight

    assert peak <= 2


# Spec: "rows are still paired with outputs in input order even when requests
# overlap; concurrent execution must not cause a later input row to consume
# the response intended for an earlier row"
def test_rows_keep_their_own_responses_when_requests_overlap(write_config, write_input, run_cli):
    def echo_with_jitter(payload, index):
        question = user_of(payload)
        return Reply(completion(f"#### {question}"), delay=0.05 * (index % 4))

    with FakeAPIServer(echo_with_jitter, capacity=64) as api:
        config_map = base_config(api.url, rpm=6000)
        config_map["task"]["rate_limits"] = {"max_concurrent": 8}
        config_map["task"]["evaluation"] = {"type": "contains", "answer_field": "answer"}
        config = write_config(config_map)
        rows = write_input([{"question": str(i), "answer": str(i)} for i in range(16)])
        result = run_cli(config, rows)

    assert [row["input"]["question"] for row in result.rows] == [str(i) for i in range(16)]
    assert all(
        row["output"]["solution"] == f"#### {row['input']['question']}" for row in result.rows
    )


# Spec: "rate_limits" values are integers; a non-integer is a config error
def test_non_integer_rate_limit_is_a_config_error(write_config, write_input, run_cli):
    config = write_config(base_config("http://x", rate_limits={"tpm": "many"}))
    result = run_cli(config, _rows(write_input))
    assert result.returncode == 1
    assert "tpm" in result.stderr

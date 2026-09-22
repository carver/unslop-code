"""Configuration and CLI surface of the Rate Limits section."""

import json

import pytest

import fake_api


def small_tokens(content="#### 5"):
    """A responder whose usage numbers are tiny, so TPM windows stay usable."""
    return fake_api.always(content, prompt_tokens=1, completion_tokens=1)


# ---------------------------------------------------------------------------
# Spec: "defaults: rate_limits: {rpm: 100, tpm: 50000, max_concurrent: 10}"
# Context: Rate Limits.  The block is accepted on a single-task config.
# ---------------------------------------------------------------------------
def test_rate_limits_block_is_accepted(run_task):
    with fake_api.FakeAPI(small_tokens()) as api:
        res = run_task(api,
                       task={"rate_limits": {"rpm": 100, "tpm": 50000,
                                             "max_concurrent": 10}},
                       check=0)
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "For multi-task configs, `defaults.rate_limits` is merged into each
#        task the same way earlier checkpoints merged `prompt`, `generation`,
#        and `evaluation`."
# Context: Rate Limits.  `max_concurrent: 1` in defaults applies to every task.
# ---------------------------------------------------------------------------
def test_defaults_rate_limits_merge_into_every_task(run_multi):
    rows = {"gsm8k": [{"question": "q%d" % i, "answer": "5"} for i in range(6)],
            "mmlu": [{"question": "m%d" % i, "answer": "B"} for i in range(6)]}
    with fake_api.FakeAPI(small_tokens(), latency=0.05) as api:
        res = run_multi(api,
                        defaults={"rate_limits": {"max_concurrent": 1}},
                        inputs=rows, check=0)
    # Two tasks, one slot each: never more than two requests in flight.
    assert api.max_inflight <= 2
    assert res.summary["total"] == 12


# ---------------------------------------------------------------------------
# Spec: "Per-task `rate_limits` keys override only the keys they specify."
# Context: Rate Limits.  `tpm` on one task leaves the merged `max_concurrent`
# from defaults in place.
# ---------------------------------------------------------------------------
def test_per_task_rate_limits_override_only_named_keys(run_multi):
    rows = {"gsm8k": [{"question": "q%d" % i, "answer": "5"} for i in range(6)],
            "mmlu": [{"question": "m%d" % i, "answer": "B"} for i in range(6)]}
    with fake_api.FakeAPI(small_tokens(), latency=0.05) as api:
        res = run_multi(api,
                        defaults={"rate_limits": {"max_concurrent": 1,
                                                  "rpm": 600}},
                        tasks={"gsm8k": {"rate_limits": {"tpm": 30000}}},
                        inputs=rows, check=0)
    assert api.max_inflight <= 2
    assert res.summary["total"] == 12


# ---------------------------------------------------------------------------
# Spec: "CLI flags: --tpm <int>"
# Context: Rate Limits.  The flag is accepted and overrides the config.
# ---------------------------------------------------------------------------
def test_tpm_cli_flag_overrides_config(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(6)]
    # One word of system prompt plus a one-word question is 2 words, so the
    # reservation is ceil(2 / 0.75) + max_tokens = 3 + 10 = 13 tokens: one
    # request fits in a 25-token window, two do not.
    with fake_api.FakeAPI(small_tokens(), latency=0.05) as api:
        res = run_task(api,
                       task={"rate_limits": {"tpm": 1000000},
                             "prompt": {"system": "Solve",
                                        "user": "{question}"},
                             "generation": {"max_tokens": 10}},
                       rows=rows, extra=["--tpm", "25"], check=0)
    assert api.max_inflight == 1
    assert res.summary["total"] == 6


# ---------------------------------------------------------------------------
# Spec: "CLI flags: --max-concurrent <int>"
# Context: Rate Limits.  The flag caps in-flight requests.
# ---------------------------------------------------------------------------
def test_max_concurrent_cli_flag(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(8)]
    with fake_api.FakeAPI(small_tokens(), latency=0.1) as api:
        res = run_task(api, task={"rpm": 600}, rows=rows,
                       extra=["--max-concurrent", "2"], check=0)
    assert api.max_inflight <= 2
    assert res.summary["total"] == 8


# ---------------------------------------------------------------------------
# Spec: "max_concurrent is a hard cap on in-flight requests independent of RPM
#        and TPM"
# Context: Rate Limits.  A generous rpm/tpm does not raise the cap.
# ---------------------------------------------------------------------------
def test_max_concurrent_caps_inflight_independently(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(10)]
    with fake_api.FakeAPI(small_tokens(), latency=0.1) as api:
        res = run_task(api,
                       task={"rate_limits": {"rpm": 600, "tpm": 1000000,
                                             "max_concurrent": 3}},
                       rows=rows, check=0)
    assert api.max_inflight <= 3
    assert res.summary["total"] == 10


# ---------------------------------------------------------------------------
# Spec: "if `rpm` is omitted, RPM limiting is disabled for that task"
# Context: Rate Limits.  A config with no rpm anywhere still runs, and runs
# concurrently rather than falling back to a slow default.
# ---------------------------------------------------------------------------
def test_rpm_omitted_disables_rpm_limiting(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(12)]
    with fake_api.FakeAPI(small_tokens(), latency=0.1) as api:
        res = run_task(api, task={"rpm": None}, rows=rows, check=0)
    assert api.max_inflight > 1
    assert res.summary["total"] == 12


# ---------------------------------------------------------------------------
# Spec: "tasks: code_gen: rate_limits: {tpm: 30000}"  (per-task override)
# Context: Rate Limits.  A single-task config carries the block too.
# ---------------------------------------------------------------------------
def test_single_task_rate_limits_override(run_task):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(4)]
    with fake_api.FakeAPI(small_tokens(), latency=0.05) as api:
        res = run_task(api,
                       task={"rpm": 600,
                             "rate_limits": {"max_concurrent": 1}},
                       rows=rows, check=0)
    assert api.max_inflight == 1
    assert res.summary["total"] == 4


# ---------------------------------------------------------------------------
# Spec: rate limit values are integers (`--tpm <int>`, `--max-concurrent <int>`)
# Context: Rate Limits.  A malformed block is a configuration error: exit 1.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("block", [
    {"tpm": "many"},
    {"max_concurrent": 0},
    {"rpm": -1},
    {"tpm": 0},
])
def test_invalid_rate_limits_are_configuration_errors(run_task, block):
    res = run_task(task={"rate_limits": block}, check=1)
    assert "error" in res.stderr.lower()


def test_rate_limits_must_be_a_mapping(run_task):
    res = run_task(task={"rate_limits": [1, 2]}, check=1)
    assert "error" in res.stderr.lower()

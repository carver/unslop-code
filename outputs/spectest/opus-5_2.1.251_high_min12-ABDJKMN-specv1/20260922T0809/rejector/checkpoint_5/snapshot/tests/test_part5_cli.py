"""Spec section: Part 5 CLI flags (--tpm, --max-concurrent, --budget,
--resume, --dry-run, --progress)."""
from __future__ import annotations

import pytest

from conftest import base_config, rows_of
from mock_server import MockAPI, always


@pytest.mark.parametrize("flag,value", [
    ("--tpm", "30000"),
    ("--max-concurrent", "4"),
    ("--budget", "25.5"),
    ("--rpm", "120"),
])
def test_value_flags_are_accepted(run_tool, write_config, write_input, flag,
                                  value):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data, extra=[flag, value])
    assert res.returncode == 0, res
    assert len(res.rows) == 2


@pytest.mark.parametrize("flag", ["--resume", "--dry-run", "--progress"])
def test_boolean_flags_are_accepted(run_tool, write_config, write_input, flag):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data, extra=[flag])
    assert res.returncode == 0, res


# Context: CLI - the flags override their config counterparts.
def test_budget_flag_overrides_config(run_tool, write_config, write_input):
    with MockAPI(always("#### 5", prompt_tokens=1000,
                        completion_tokens=1000)) as api:
        cfg = write_config(base_config(
            api.url,
            cost={"prompt_cost_per_1k": 0.01, "completion_cost_per_1k": 0.03,
                  "budget": 100.0}))
        data = write_input(rows_of(2))
        res = run_tool(cfg, data, extra=["--budget", "7.5"])
    assert res.returncode == 0, res
    assert res.summary["cost"]["budget"] == 7.5


def test_max_concurrent_flag_overrides_config(run_tool, write_config,
                                              write_input):
    with MockAPI(always("#### 5"), delay=0.15) as api:
        cfg = write_config(base_config(api.url,
                                       rate_limits={"max_concurrent": 16}))
        data = write_input(rows_of(12))
        res = run_tool(cfg, data, extra=["--max-concurrent", "2"])
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert peak <= 2, peak


# Context: CLI - a non-numeric value for a numeric flag is a usage error.
@pytest.mark.parametrize("flag,value", [
    ("--tpm", "lots"),
    ("--max-concurrent", "x"),
    ("--budget", "cheap"),
])
def test_bad_flag_values_exit_1(run_tool, write_config, write_input, flag,
                                value):
    cfg = write_config(base_config("http://127.0.0.1:1"))
    data = write_input(rows_of(1))
    res = run_tool(cfg, data, extra=[flag, value])
    assert res.returncode == 1, res

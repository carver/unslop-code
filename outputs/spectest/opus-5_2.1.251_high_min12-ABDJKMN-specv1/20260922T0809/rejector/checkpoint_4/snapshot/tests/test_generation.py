"""Spec section: Generation behavior (greedy / sample / rejection)."""
from __future__ import annotations

from conftest import base_config
from mock_server import MockAPI, always, completion, sequence


# ---------------------------------------------------------------------------
# Phrase: "greedy: force temperature to 0.0"
# Context: Configuration / Generation behavior.  A non-zero configured
# temperature is overridden.
# ---------------------------------------------------------------------------
def test_greedy_forces_temperature_zero(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url, generation={"scheme": "greedy", "temperature": 0.9}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["temperature"] == 0.0


# Context: same phrase - a --temperature override is also forced to 0.0.
def test_greedy_forces_temperature_zero_over_cli(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data, extra=["--temperature", "1.2"])
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["temperature"] == 0.0


# ---------------------------------------------------------------------------
# Phrase: "greedy: ... n is ignored"
# Context: Generation behavior.  One API call, one logical attempt.
# ---------------------------------------------------------------------------
def test_greedy_ignores_n(run_tool, write_config, write_input):
    with MockAPI(always("#### 7")) as api:
        cfg = write_config(base_config(
            api.url, generation={"scheme": "greedy", "n": 5}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert calls == 1
    assert res.rows[0]["result"]["attempts"] == 1
    # `n` is not part of the documented request body.
    assert "n" not in sent


# ---------------------------------------------------------------------------
# Phrase: "sample: temperature must be > 0; n is ignored"
# Context: Generation behavior.
# ---------------------------------------------------------------------------
def test_sample_sends_configured_temperature_and_ignores_n(run_tool,
                                                           write_config,
                                                           write_input):
    with MockAPI(always("#### 7")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "sample", "temperature": 0.7, "n": 4}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["temperature"] == 0.7
    assert calls == 1
    assert res.rows[0]["result"]["attempts"] == 1


# ---------------------------------------------------------------------------
# Phrase: "rejection: ... make up to n attempts and keep the first passing
#          response"
# Context: Generation behavior.  The spec's example: n=3, first two responses
# fail, the third passes -> attempts 3, third response kept, three meta entries.
# ---------------------------------------------------------------------------
def test_rejection_keeps_first_passing_response(run_tool, write_config,
                                                write_input):
    responder = sequence(["#### 1", "#### 2", "#### 5", "#### 9"])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    row = res.rows[0]
    assert calls == 3
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5",
                             "attempts": 3}
    assert isinstance(row["meta"], list)
    assert len(row["meta"]) == 3


# Context: same phrase - "up to n": sampling stops as soon as one passes.
def test_rejection_stops_at_first_pass(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 5}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1
    assert res.rows[0]["result"]["attempts"] == 1


# ---------------------------------------------------------------------------
# Phrase: "if all attempts fail, output null with "passed": false"
# Context: Generation behavior, mirrored by the rejection-exhaustion output
# example (attempts 5, meta list of 5).
# ---------------------------------------------------------------------------
def test_rejection_exhausted(run_tool, write_config, write_input):
    with MockAPI(always("#### 1")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 5}))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    row = res.rows[0]
    assert calls == 5
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None,
                             "attempts": 5}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 5


# ---------------------------------------------------------------------------
# Phrase: "rejection: temperature must be > 0" (the value actually sent)
# Context: Generation behavior.
# ---------------------------------------------------------------------------
def test_rejection_sends_configured_temperature_each_attempt(run_tool,
                                                             write_config,
                                                             write_input):
    with MockAPI(always("nope")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.65, "n": 3}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        temps = [r["temperature"] for r in api.requests]
    assert res.returncode == 0, res
    assert temps == [0.65, 0.65, 0.65]


# Context (ambiguity T2): a rejection row that passes on attempt 1 emits a bare
# meta object, not a one-element list.
def test_rejection_single_attempt_meta_is_object(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert isinstance(res.rows[0]["meta"], dict)


# Context (ambiguity T7): a hard API failure during rejection fails the row.
def test_rejection_hard_api_failure_fails_row(run_tool, write_config,
                                              write_input):
    with MockAPI(lambda req, i: (500, {"e": 1})) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 4}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    # 3 requests for the first attempt, then the row is abandoned.
    assert calls == 3
    assert res.rows[0]["output"] is None
    assert res.rows[0]["result"]["passed"] is False


# Context: "rejection ... 1..n for result.attempts" with n defaulting to 1.
def test_rejection_with_n_one(run_tool, write_config, write_input):
    with MockAPI(always("#### 9")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 1}))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1
    row = res.rows[0]
    assert row["result"]["attempts"] == 1
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert isinstance(row["meta"], dict)

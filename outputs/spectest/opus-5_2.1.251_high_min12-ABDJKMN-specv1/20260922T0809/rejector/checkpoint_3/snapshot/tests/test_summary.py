"""Spec section: Output / summary object and its rules."""
from __future__ import annotations

import json

from conftest import base_config
from mock_server import MockAPI, always, completion, sequence


# ---------------------------------------------------------------------------
# Phrase: "After processing finishes, print one JSON summary object to stdout."
# Context: Output.  Exactly one JSON object, with the documented keys.
# ---------------------------------------------------------------------------
def test_summary_is_single_json_object_on_stdout(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    lines = [l for l in res.stdout.splitlines() if l.strip()]
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert set(summary) == {
        "total", "passed", "failed", "total_prompt_tokens",
        "total_completion_tokens", "total_api_calls", "elapsed_seconds",
        "throughput_rpm",
    }


# ---------------------------------------------------------------------------
# Phrase: "total: input row count"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_total_is_row_count(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(7)])
        res = run_tool(cfg, data)
    assert res.summary["total"] == 7


# ---------------------------------------------------------------------------
# Phrase: "passed: rows where result.passed is true"
#         "failed: rows where result.passed is false or output is null"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_passed_and_failed_counts(run_tool, write_config, write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        return 200, completion("#### 5" if user.startswith("good") else "#### 0")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url))
        rows = [{"question": "good1", "answer": "5"},
                {"question": "bad1", "answer": "5"},
                {"question": "good2", "answer": "5"},
                {"question": "bad2", "answer": "5"},
                {"question": "bad3", "answer": "5"}]
        data = write_input(rows)
        res = run_tool(cfg, data)
    s = res.summary
    assert (s["total"], s["passed"], s["failed"]) == (5, 2, 3)


# ---------------------------------------------------------------------------
# Phrase: "when no evaluation is configured, treat successful API rows as
#          passed"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_no_evaluation_counts_successful_rows_as_passed(run_tool, write_config,
                                                        write_input):
    with MockAPI(always("whatever")) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": f"q{i}"} for i in range(3)])
        res = run_tool(cfg, data)
    s = res.summary
    assert (s["total"], s["passed"], s["failed"]) == (3, 3, 0)
    assert all(r["result"]["passed"] is None for r in res.rows)


# Context: same phrase - a row with null output is failed even with no
# evaluation configured.
def test_no_evaluation_null_output_counts_as_failed(run_tool, write_config,
                                                    write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        if user == "dead":
            return 500, {"e": 1}
        return 200, completion("fine")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": "dead"}, {"question": "alive"}])
        res = run_tool(cfg, data)
    s = res.summary
    assert (s["total"], s["passed"], s["failed"]) == (2, 1, 1)


# ---------------------------------------------------------------------------
# Phrase: "total_prompt_tokens" / "total_completion_tokens"
# Context: Output summary block.
# ---------------------------------------------------------------------------
def test_token_totals(run_tool, write_config, write_input):
    body = completion("#### 5", prompt_tokens=45, completion_tokens=120)
    with MockAPI(lambda req, i: (200, body)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(4)])
        res = run_tool(cfg, data)
    s = res.summary
    assert s["total_prompt_tokens"] == 180
    assert s["total_completion_tokens"] == 480


# Context: same phrase - rejection attempts all contribute their tokens.
def test_token_totals_include_every_attempt(run_tool, write_config,
                                            write_input):
    responder = sequence([
        (200, completion("#### 1", prompt_tokens=10, completion_tokens=1)),
        (200, completion("#### 2", prompt_tokens=10, completion_tokens=2)),
        (200, completion("#### 42", prompt_tokens=10, completion_tokens=3)),
    ])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 5}))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
    s = res.summary
    assert s["total_prompt_tokens"] == 30
    assert s["total_completion_tokens"] == 6


# ---------------------------------------------------------------------------
# Phrase: "total_api_calls: all HTTP requests, including retries and rejection
#          attempts"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_total_api_calls_includes_retries_and_attempts(run_tool, write_config,
                                                       write_input):
    # Row "a": 500, 500, then a failing answer -> attempt 2 passes.
    # Row "b": passes immediately.
    state = {}

    def responder(req, i):
        user = req["messages"][-1]["content"]
        count = state.get(user, 0)
        state[user] = count + 1
        if user == "a":
            if count < 2:
                return 500, {"e": 1}
            if count == 2:
                return 200, completion("#### 0")
            return 200, completion("#### 5")
        return 200, completion("#### 5")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": "a", "answer": "5"},
                            {"question": "b", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert res.summary["total_api_calls"] == calls == 5
    assert res.rows[0]["result"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Phrase: "elapsed_seconds: wall-clock time from first request to last
#          response, rounded to 1 decimal place"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_elapsed_seconds_rounded_to_one_decimal(run_tool, write_config,
                                                write_input):
    with MockAPI(always("#### 5"), delay=0.5) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    elapsed = res.summary["elapsed_seconds"]
    assert isinstance(elapsed, float)
    assert round(elapsed, 1) == elapsed
    assert 0.4 <= elapsed <= 5.0


# ---------------------------------------------------------------------------
# Phrase: "throughput_rpm: total_api_calls / elapsed_seconds * 60, rounded to
#          1 decimal place"
# Context: Summary rules.
# ---------------------------------------------------------------------------
def test_throughput_matches_formula(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.2) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(10)])
        res = run_tool(cfg, data)
    s = res.summary
    assert round(s["throughput_rpm"], 1) == s["throughput_rpm"]
    expected = s["total_api_calls"] / s["elapsed_seconds"] * 60
    # Elapsed is reported rounded, so allow for that quantisation.
    assert abs(s["throughput_rpm"] - expected) < max(1.0, expected * 0.1)


# ---------------------------------------------------------------------------
# Phrase (ambiguity T17): an empty input file still produces a summary.
# Context: Summary rules / "total: input row count".
# ---------------------------------------------------------------------------
def test_empty_input_summary(run_tool, write_config, write_input, workdir):
    out = workdir / "results.jsonl"
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([])
        res = run_tool(cfg, data, output=str(out))
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 0
    assert out.read_text() == ""
    s = res.summary
    assert s["total"] == 0 and s["passed"] == 0 and s["failed"] == 0
    assert s["total_api_calls"] == 0
    assert s["elapsed_seconds"] == 0.0
    assert s["throughput_rpm"] == 0.0


# Context: Summary rules - passed + failed partitions total.
def test_passed_plus_failed_equals_total(run_tool, write_config, write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        if user.endswith("0"):
            return 500, {"e": 1}
        return 200, completion("#### 5" if user.endswith("1") else "#### 9")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(6)])
        res = run_tool(cfg, data)
    s = res.summary
    assert s["passed"] + s["failed"] == s["total"] == 6

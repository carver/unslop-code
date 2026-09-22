"""Spec section: Rate Limits (sliding RPM/TPM windows, max_concurrent)."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

from conftest import (AGENTIC_ROW, GSM8K_TASK, JUDGE_TASK, LOOKUP_TOOL,
                      MMLU_TASK, agentic_config, agentic_replies, base_config,
                      judge_responder, multi_config, rows_of)
from mock_server import MockAPI, always, completion

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rejector  # noqa: E402


def settle(seconds=2.5):
    time.sleep(seconds)


# ---------------------------------------------------------------------------
# Phrase: "defaults: rate_limits: rpm: 100 / tpm: 50000 / max_concurrent: 10"
# Context: Rate Limits configuration.  The block parses and the run works.
# ---------------------------------------------------------------------------
def test_rate_limits_block_is_accepted(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url,
            rate_limits={"rpm": 100, "tpm": 50000, "max_concurrent": 10}))
        data = write_input(rows_of(3))
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert len(res.rows) == 3


# ---------------------------------------------------------------------------
# Phrase: "For multi-task configs, `defaults.rate_limits` is merged into each
#          task the same way earlier checkpoints merged `prompt`..."
# Context: Rate Limits.  max_concurrent from `defaults` applies to every task.
# ---------------------------------------------------------------------------
def test_defaults_rate_limits_merge_into_every_task(run_tool, write_config,
                                                    write_input, workdir):
    with MockAPI(always("#### 5"), delay=0.2) as api:
        cfg = write_config(multi_config(
            api.url, {"gsm8k": GSM8K_TASK, "mmlu": MMLU_TASK},
            defaults={"rate_limits": {"max_concurrent": 1}}))
        a = write_input(rows_of(4), name="a.jsonl")
        b = write_input([{"question": f"q{i}", "a": "1", "b": "2", "c": "3",
                          "d": "4", "answer": "A"} for i in range(4)],
                        name="b.jsonl")
        res = run_tool(cfg, [f"gsm8k={a}", f"mmlu={b}"],
                       output=str(workdir / "out"))
        peak = api.max_inflight
    assert res.returncode == 0, res
    # One slot per task, two tasks running concurrently.
    assert peak <= 2, peak


# ---------------------------------------------------------------------------
# Phrase: "Per-task `rate_limits` keys override only the keys they specify."
# Context: Rate Limits.  `tasks.code_gen.rate_limits.tpm` replaces the default
# tpm while rpm and max_concurrent survive from `defaults`.
# ---------------------------------------------------------------------------
def test_per_task_rate_limits_override_single_key(run_tool, write_config,
                                                  write_input, workdir):
    with MockAPI(always("#### 5"), delay=0.2) as api:
        tasks = {"gsm8k": dict(GSM8K_TASK),
                 "mmlu": dict(MMLU_TASK, rate_limits={"tpm": 30000})}
        cfg = write_config(multi_config(
            api.url, tasks,
            defaults={"rate_limits": {"rpm": 600, "tpm": 50000,
                                      "max_concurrent": 1}}))
        a = write_input(rows_of(3), name="a.jsonl")
        b = write_input([{"question": f"q{i}", "a": "1", "b": "2", "c": "3",
                          "d": "4", "answer": "A"} for i in range(3)],
                        name="b.jsonl")
        res = run_tool(cfg, [f"gsm8k={a}", f"mmlu={b}"],
                       output=str(workdir / "out"))
        peak = api.max_inflight
    assert res.returncode == 0, res
    # mmlu only overrode `tpm`; `max_concurrent: 1` still applies to it.
    assert peak <= 2, peak
    assert len(res.rows_for("mmlu")) == 3


# ---------------------------------------------------------------------------
# Phrase: "CLI flags: --tpm <int>, --max-concurrent <int>"
# Context: Rate Limits.  Both flags are accepted and override the config.
# ---------------------------------------------------------------------------
def test_tpm_and_max_concurrent_flags(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.2) as api:
        cfg = write_config(base_config(
            api.url, rate_limits={"max_concurrent": 8}))
        data = write_input(rows_of(6))
        res = run_tool(cfg, data,
                       extra=["--tpm", "500000", "--max-concurrent", "2"])
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert peak <= 2, peak


# ---------------------------------------------------------------------------
# Phrase: "continue to enforce RPM, now using a sliding 60-second window"
# Context: Rate Limits.  With rpm: 5 only five requests may be sent in the
# first minute; the sixth waits for the window to slide.
# ---------------------------------------------------------------------------
def test_rpm_sliding_window_caps_first_minute(run_tool_bg, write_config,
                                              write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, rpm=None,
                                       rate_limits={"rpm": 5}))
        data = write_input(rows_of(12))
        run = run_tool_bg(cfg, data)
        settle(4)
        count = api.call_count
        run.stop()
    assert count == 5, count


# ---------------------------------------------------------------------------
# Phrase: "if `rpm` is omitted, RPM limiting is disabled for that task"
# Context: Rate Limits.  No rpm anywhere: every row goes out at once.
# ---------------------------------------------------------------------------
def test_rpm_omitted_disables_rpm_limiting(run_tool, write_config,
                                           write_input):
    with MockAPI(always("#### 5"), delay=0.1) as api:
        cfg = write_config(base_config(api.url, rpm=None))
        data = write_input(rows_of(30))
        start = time.time()
        res = run_tool(cfg, data)
        wall = time.time() - start
    assert res.returncode == 0, res
    assert len(res.rows) == 30
    assert wall < 20, wall


# ---------------------------------------------------------------------------
# Phrase: "before sending a request, estimate prompt tokens by counting words
#          in the rendered messages using `1 token ~= 0.75 words`, rounded up"
# Context: Rate Limits.  ceil(words / 0.75) tokens.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,words", [
    ("one two three", 3),
    ("a", 1),
    ("alpha beta gamma delta epsilon zeta", 6),
    ("  spaced   out   words  ", 3),
])
def test_prompt_token_estimate_uses_word_count(text, words):
    assert rejector.estimate_tokens(text) == math.ceil(words / 0.75)


def test_prompt_token_estimate_of_messages():
    messages = [{"role": "system", "content": "one two three"},
                {"role": "user", "content": "four five"}]
    assert rejector.estimate_message_tokens(messages) == math.ceil(5 / 0.75)


# ---------------------------------------------------------------------------
# Phrase: "reserve against `estimated_prompt_tokens + max_tokens` before
#          dispatch"
# Context: Rate Limits.  With a slow server no response has landed yet, so the
# only thing holding requests back is the reservation.
# ---------------------------------------------------------------------------
def test_tpm_reservation_is_made_before_dispatch(run_tool_bg, write_config,
                                                 write_input):
    # Each reservation is ~ceil(words/0.75) + 1000 tokens; 2500 fits two.
    with MockAPI(always("#### 5"), delay=5.0) as api:
        cfg = write_config(base_config(
            api.url, rpm=None,
            generation={"max_tokens": 1000},
            rate_limits={"tpm": 2500, "max_concurrent": 10}))
        data = write_input(rows_of(8))
        run = run_tool_bg(cfg, data)
        settle(2.5)
        count = api.call_count
        run.stop()
    assert count == 2, count


# ---------------------------------------------------------------------------
# Phrase: "when `tpm` is configured, also enforce a sliding 60-second token
#          budget" / "after the response arrives, record actual `prompt_tokens
#          + completion_tokens` from the API response in the TPM window"
# Context: Rate Limits.  The reservation is ~515 tokens (15 estimated prompt
# tokens + max_tokens 500), so a 1200-token window would fit two requests; the
# response reports 1000 actual tokens, and once that is recorded the window has
# no room for a second request.
# ---------------------------------------------------------------------------
def test_tpm_window_counts_actual_response_tokens(run_tool_bg, write_config,
                                                  write_input):
    def responder(req, i):
        return 200, completion("#### 5", prompt_tokens=500,
                               completion_tokens=500)

    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url, rpm=None,
            generation={"max_tokens": 500},
            rate_limits={"tpm": 1200, "max_concurrent": 1}))
        data = write_input(rows_of(8))
        run = run_tool_bg(cfg, data)
        settle(3)
        count = api.call_count
        run.stop()
    assert count == 1, count


# ---------------------------------------------------------------------------
# Phrase: "if both RPM and TPM are configured, a request may be sent only when
#          both budgets have capacity"
# Context: Rate Limits / "TPM bottleneck": rpm is generous, tpm is the binding
# limit, so the scheduler paces on tokens.
# ---------------------------------------------------------------------------
def test_tpm_binds_when_rpm_is_generous(run_tool_bg, write_config,
                                        write_input):
    def responder(req, i):
        return 200, completion("#### 5", prompt_tokens=112,
                               completion_tokens=500)

    with MockAPI(responder) as api:
        # ~612 actual tokens per call against tpm 2000: three calls at most.
        cfg = write_config(base_config(
            api.url, rpm=None,
            generation={"max_tokens": 500},
            rate_limits={"rpm": 600, "tpm": 2000, "max_concurrent": 1}))
        data = write_input(rows_of(20))
        run = run_tool_bg(cfg, data)
        settle(3)
        count = api.call_count
        run.stop()
    assert count <= 4, count
    assert count >= 2, count


# Context: Rate Limits - the mirror case, rpm binds while tpm is generous.
def test_rpm_binds_when_tpm_is_generous(run_tool_bg, write_config,
                                        write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(
            api.url, rpm=None,
            rate_limits={"rpm": 3, "tpm": 10 ** 9, "max_concurrent": 10}))
        data = write_input(rows_of(12))
        run = run_tool_bg(cfg, data)
        settle(3)
        count = api.call_count
        run.stop()
    assert count == 3, count


# ---------------------------------------------------------------------------
# Phrase: "`max_concurrent` is a hard cap on in-flight requests independent of
#          RPM and TPM"
# Context: Rate Limits.
# ---------------------------------------------------------------------------
def test_max_concurrent_is_a_hard_cap(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.15) as api:
        cfg = write_config(base_config(
            api.url, rate_limits={"rpm": 600, "tpm": 10 ** 9,
                                  "max_concurrent": 3}))
        data = write_input(rows_of(24))
        res = run_tool(cfg, data)
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert peak <= 3, peak
    assert peak > 1, peak


# ---------------------------------------------------------------------------
# Phrase: "rows are still paired with outputs in input order even when requests
#          overlap; concurrent execution must not cause a later input row to
#          consume the response intended for an earlier row"
# Context: Rate Limits.
# ---------------------------------------------------------------------------
def test_rows_stay_paired_under_rate_limiting(run_tool, write_config,
                                              write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        index = int(user[1:])
        time.sleep(max(0.0, (10 - index) * 0.03))
        return 200, completion(f"#### {index}")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url, rate_limits={"rpm": 600, "tpm": 10 ** 9,
                                  "max_concurrent": 6}))
        data = write_input([{"question": f"q{i}", "answer": str(i)}
                            for i in range(10)])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    for i, row in enumerate(res.rows):
        assert row["input"]["question"] == f"q{i}"
        assert row["output"]["solution"] == f"#### {i}"


# ---------------------------------------------------------------------------
# Phrase: "each `llm_judge` call goes through the same limiter"
# Context: Rate Limits.  Two rows need two generation and two judge calls;
# rpm: 3 lets only three of them through in the first window.
# ---------------------------------------------------------------------------
def _judge_config(api_url, **over):
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only a "
                      "single integer from 1 to 10.",
            "user": "Rate this response:\n{__response__}\n\nScore:",
        },
        "threshold": 7,
        "extract": "first_number",
        "answer_field": None,
    }
    return base_config(api_url, evaluation=evaluation,
                       output_field="response", **over)


def test_judge_calls_consume_rpm(run_tool_bg, write_config, write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(
            api.url, rpm=None,
            prompt={"system": "You are a writer.", "user": "{prompt_text}"},
            rate_limits={"rpm": 3, "max_concurrent": 5}))
        data = write_input([{"prompt_text": f"p{i}"} for i in range(4)])
        run = run_tool_bg(cfg, data)
        settle(3)
        count = api.call_count
        run.stop()
    assert count == 3, count


def test_judge_calls_respect_max_concurrent(run_tool, write_config,
                                            write_input):
    with MockAPI(judge_responder(), delay=0.1) as api:
        cfg = write_config(_judge_config(
            api.url,
            prompt={"system": "You are a writer.", "user": "{prompt_text}"},
            rate_limits={"max_concurrent": 2}))
        data = write_input([{"prompt_text": f"p{i}"} for i in range(6)])
        res = run_tool(cfg, data)
        peak = api.max_inflight
    assert res.returncode == 0, res
    assert peak <= 2, peak


# ---------------------------------------------------------------------------
# Phrase: "for agentic loops, every API request counts toward RPM and TPM"
# Context: Rate Limits.  A single row runs three iterations; rpm: 2 stops the
# loop's third request inside the first window.
# ---------------------------------------------------------------------------
def test_agentic_iterations_consume_rpm(run_tool_bg, write_config,
                                        write_input):
    script = [[("lookup", {"key": "revenue_q1"})],
              [("lookup", {"key": "revenue_q2"})],
              "#### 2730000"]
    with MockAPI(agentic_replies(script)) as api:
        cfg = write_config(agentic_config(
            api.url, [LOOKUP_TOOL], rpm=None,
            rate_limits={"rpm": 2, "max_concurrent": 5}))
        data = write_input([AGENTIC_ROW])
        run = run_tool_bg(cfg, data)
        settle(3)
        count = api.call_count
        run.stop()
    assert count == 2, count


# ---------------------------------------------------------------------------
# Phrase: "the loop holds one concurrency slot for its entire lifetime"
# Context: Rate Limits.  With max_concurrent: 1 two agentic rows may not
# interleave: every request of the first loop precedes the second loop's.
# ---------------------------------------------------------------------------
def test_agentic_loop_holds_its_slot(run_tool, write_config, write_input):
    script = [[("lookup", {"key": "revenue_q1"})], "#### 2730000"]
    with MockAPI(agentic_replies(script), delay=0.05) as api:
        cfg = write_config(agentic_config(
            api.url, [LOOKUP_TOOL], rpm=None,
            rate_limits={"max_concurrent": 1}))
        data = write_input([dict(AGENTIC_ROW, question=f"q{i}")
                            for i in range(3)])
        res = run_tool(cfg, data)
        peak = api.max_inflight
        questions = [req["messages"][1]["content"] for req in api.requests]
    assert res.returncode == 0, res
    assert peak == 1, peak
    # Loops run one at a time: the question sequence is grouped, not striped.
    assert questions == ["q0", "q0", "q1", "q1", "q2", "q2"], questions

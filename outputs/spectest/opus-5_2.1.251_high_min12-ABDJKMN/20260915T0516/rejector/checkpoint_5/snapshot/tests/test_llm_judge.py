"""`llm_judge` evaluation: the judge call, its score, and its metadata."""
import json

import pytest

from conftest import make_config, make_multi_config, judge_task
from mock_api import MockAPI, always, by_text, message_text, sequence

JUDGE_MARK = "Rate this response"
ROW = {"prompt_text": "Write about cats", "criteria": "clarity"}


def judge_config(threshold=7, extract="first_number", model=None, api_url=None,
                 scheme="greedy", temperature=None, n=None,
                 judge_system="JUDGE SYSTEM. Reply with an integer."):
    judge_prompt = {"user": "Rate this response:\n{__response__}\n\n"
                            "Criteria: {criteria}\n\nScore:"}
    if judge_system is not None:
        judge_prompt["system"] = judge_system
    evaluation = {"type": "llm_judge", "judge_prompt": judge_prompt,
                  "threshold": threshold}
    if extract is not None:
        evaluation["extract"] = extract
    if model is not None:
        evaluation["model"] = model
    return make_config(api_url=api_url, evaluation=evaluation,
                       user="{prompt_text}", system="Write a response.",
                       output_field="response", scheme=scheme,
                       temperature=temperature, n=n)


def responder(score="8", generation="A fine essay about cats."):
    return by_text([(JUDGE_MARK, score)], default=generation)


def judge_calls(api):
    return [c for c in api.calls if JUDGE_MARK in message_text(c)]


def generation_calls(api):
    return [c for c in api.calls if JUDGE_MARK not in message_text(c)]


# Spec: "the judge request is a separate API call through the same server"
# Context: `llm_judge` evaluation rules.
def test_judge_makes_a_second_call_to_the_same_server(run_tool):
    with MockAPI(responder()) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert len(judge_calls(api)) == 1
    assert set(api.paths) == {"/v1/chat/completions"}


# Spec: "generation response is produced first / judge prompt is rendered with
# `__response__` / if the judge returns `"8"`, then `judge_score` is `8`"
# Context: Examples, "LLM judge example".
def test_spec_judge_example(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(threshold=7, api_url=api.url), [ROW])
    row = run.rows[0]
    assert row["output"] == {"response": "A fine essay about cats."}
    assert row["result"]["judge_score"] == 8
    assert row["result"]["passed"] is True


# Spec: "`__response__` is the generated response text"
# Context: `llm_judge` evaluation rules.
def test_judge_prompt_contains_the_generated_response(run_tool):
    with MockAPI(responder(generation="THE GENERATED TEXT")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    user = message_text(judge_calls(api)[0], "user")
    assert "THE GENERATED TEXT" in user


# Spec: "`judge_prompt` uses the same template rules as normal prompts"
# Context: `llm_judge` evaluation rules; row fields resolve as usual.
def test_judge_prompt_resolves_row_fields(run_tool):
    with MockAPI(responder()) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    user = message_text(judge_calls(api)[0], "user")
    assert "Criteria: clarity" in user


def test_judge_prompt_sends_its_own_system_message(run_tool):
    with MockAPI(responder()) as api:
        run = run_tool(judge_config(api_url=api.url,
                                    judge_system="JUDGE SYSTEM LINE"), [ROW])
    assert message_text(judge_calls(api)[0], "system") == "JUDGE SYSTEM LINE"


def test_judge_prompt_without_system_sends_only_a_user_message(run_tool):
    with MockAPI(responder()) as api:
        run = run_tool(judge_config(api_url=api.url, judge_system=None), [ROW])
    roles = [m["role"] for m in judge_calls(api)[0]["messages"]]
    assert roles == ["user"]


def test_missing_judge_prompt_field_in_a_row_exits_1(run_tool):
    with MockAPI(responder()) as api:
        run = run_tool(judge_config(api_url=api.url),
                       [{"prompt_text": "no criteria field here"}])
    assert run.returncode == 1
    assert "criteria" in run.stderr


# Spec: "score `>= threshold` passes"
# Context: `llm_judge` evaluation rules.
@pytest.mark.parametrize("score,passed", [
    ("9", True), ("7", True), ("6", False), ("1", False), ("10", True),
])
def test_threshold_comparison(run_tool, score, passed):
    with MockAPI(responder(score)) as api:
        run = run_tool(judge_config(threshold=7, api_url=api.url), [ROW])
    assert run.rows[0]["result"]["passed"] is passed
    assert run.rows[0]["result"]["judge_score"] == int(score)
    assert run.summary["passed"] == (1 if passed else 0)


def test_decimal_judge_score_is_kept(run_tool):
    with MockAPI(responder("8.5")) as api:
        run = run_tool(judge_config(threshold=7, api_url=api.url), [ROW])
    assert run.rows[0]["result"]["judge_score"] == 8.5
    assert run.rows[0]["result"]["passed"] is True


def test_judge_score_is_extracted_from_a_wordy_reply(run_tool):
    with MockAPI(responder("Score: 9 because it is clear")) as api:
        run = run_tool(judge_config(threshold=7, api_url=api.url), [ROW])
    assert run.rows[0]["result"]["judge_score"] == 9


# T27: a judge reply with no number cannot clear the threshold.
def test_unparseable_judge_reply_fails_the_row(run_tool):
    with MockAPI(responder("excellent work")) as api:
        run = run_tool(judge_config(threshold=7, api_url=api.url), [ROW])
    assert run.rows[0]["result"]["judge_score"] is None
    assert run.rows[0]["result"]["passed"] is False


# T42: `extract` defaults to `first_number` for a judge score.
def test_extract_defaults_to_first_number(run_tool):
    with MockAPI(responder("8 out of 10")) as api:
        run = run_tool(judge_config(extract=None, threshold=7, api_url=api.url),
                       [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["judge_score"] == 8


# Spec: "`result` includes `judge_score`"
# Context: `llm_judge` evaluation rules.
def test_result_block_keeps_the_part_1_keys_and_adds_judge_score(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    result = run.rows[0]["result"]
    assert set(result) == {"passed", "extracted_answer", "attempts",
                           "judge_score"}
    assert result["attempts"] == 1


# Spec: "`meta` includes a `judge_meta` object with the judge request's token
# usage, latency, model, and finish reason"
# Context: `llm_judge` evaluation rules.
def test_meta_includes_judge_meta(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    meta = run.rows[0]["meta"]
    judge_meta = meta["judge_meta"]
    assert judge_meta["model"] == "gpt-4"
    assert judge_meta["finish_reason"] == "stop"
    assert judge_meta["prompt_tokens"] == 45
    assert judge_meta["completion_tokens"] == 120
    assert judge_meta["total_tokens"] == 165
    assert isinstance(judge_meta["latency_ms"], int)


def test_generation_meta_is_still_reported_alongside_judge_meta(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    meta = run.rows[0]["meta"]
    for key in ("model", "prompt_tokens", "completion_tokens", "total_tokens",
                "latency_ms", "finish_reason"):
        assert key in meta
    assert "judge_meta" not in meta["judge_meta"]


# Spec: "if `evaluation.model` is omitted, use the task's model"
# Context: `llm_judge` evaluation rules.
def test_judge_uses_the_task_model_by_default(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    assert judge_calls(api)[0]["model"] == "gpt-4"


def test_evaluation_model_overrides_the_judge_model(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url, model="judge-model"),
                       [ROW])
    assert run.returncode == 0, run.stderr
    assert judge_calls(api)[0]["model"] == "judge-model"
    assert generation_calls(api)[0]["model"] == "gpt-4"
    assert run.rows[0]["meta"]["judge_meta"]["model"] == "judge-model"


# Spec: "judge calls count toward throughput, `total_api_calls`, and per-task
# API call totals"
# Context: `llm_judge` evaluation rules.
def test_judge_calls_count_toward_total_api_calls(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW, ROW, ROW])
    assert api.call_count == 6
    assert run.summary["total_api_calls"] == 6
    assert run.summary["total"] == 3


def test_judge_calls_count_toward_throughput(run_tool):
    # a measurable service time, so elapsed_seconds does not round to 0.0
    with MockAPI(responder("8"), service_seconds=0.3) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW, ROW])
    summary = run.summary
    expected = summary["total_api_calls"] / summary["elapsed_seconds"] * 60.0
    assert summary["throughput_rpm"] == pytest.approx(expected, rel=0.15)


def test_judge_token_usage_counts_toward_the_totals(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    # one generation call plus one judge call, 45/120 tokens each
    assert run.summary["total_prompt_tokens"] == 90
    assert run.summary["total_completion_tokens"] == 240


# Rejection sampling judges every attempt and stops at the first pass.
def test_rejection_judges_each_attempt(run_tool):
    scores = iter(["3", "4", "9"])

    def judging(payload, i):
        from mock_api import chat_response
        if JUDGE_MARK in message_text(payload):
            return 200, chat_response(next(scores))
        return 200, chat_response("draft")

    with MockAPI(judging) as api:
        run = run_tool(judge_config(api_url=api.url, scheme="rejection",
                                    temperature=0.8, n=5), [ROW])
    row = run.rows[0]
    assert run.returncode == 0, run.stderr
    assert row["result"]["attempts"] == 3
    assert row["result"]["judge_score"] == 9
    assert row["result"]["passed"] is True
    assert isinstance(row["meta"], list) and len(row["meta"]) == 3
    assert [m["judge_meta"] is not None for m in row["meta"]] == [True] * 3
    assert run.summary["total_api_calls"] == 6


def test_rejection_that_never_passes_the_judge_fails_the_row(run_tool):
    with MockAPI(responder("2")) as api:
        run = run_tool(judge_config(api_url=api.url, scheme="rejection",
                                    temperature=0.8, n=2), [ROW])
    row = run.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["attempts"] == 2


# A generation that never succeeds is failed without a judge call.
def test_no_judge_call_when_generation_fails(run_tool):
    from mock_api import status
    with MockAPI(status(500)) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    assert run.rows[0]["output"] is None
    assert run.rows[0]["result"]["judge_score"] is None
    assert run.rows[0]["result"]["passed"] is False
    assert judge_calls(api) == []


# T33: a judge call that never answers fails the row.
def test_failed_judge_call_fails_the_row(run_tool):
    def flaky(payload, i):
        from mock_api import chat_response
        if JUDGE_MARK in message_text(payload):
            return 500, {"error": "boom"}
        return 200, chat_response("draft")

    with MockAPI(flaky) as api:
        run = run_tool(judge_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False
    assert run.rows[0]["result"]["judge_score"] is None
    assert run.rows[0]["meta"]["judge_meta"] is None
    # retries still count: 1 generation + 3 judge attempts
    assert run.summary["total_api_calls"] == 4


# Configuration validation for the new type.
def test_llm_judge_without_judge_prompt_exits_1(run_tool):
    config = make_config(evaluation={"type": "llm_judge", "threshold": 7},
                         user="{prompt_text}")
    run = run_tool(config, [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_llm_judge_without_threshold_exits_1(run_tool):
    config = make_config(
        evaluation={"type": "llm_judge",
                    "judge_prompt": {"user": "Rate {__response__}"}},
        user="{prompt_text}")
    run = run_tool(config, [ROW])
    assert run.returncode == 1
    assert run.stderr.strip()


def test_llm_judge_without_judge_prompt_user_exits_1(run_tool):
    config = make_config(
        evaluation={"type": "llm_judge", "threshold": 7,
                    "judge_prompt": {"system": "judge"}},
        user="{prompt_text}")
    run = run_tool(config, [ROW])
    assert run.returncode == 1


# Multi-task: a judge task beside a plain task.
def test_judge_task_inside_a_multi_task_config(multi):
    cfg = make_multi_config(tasks={"review": judge_task(threshold=7)})
    with MockAPI(by_text([("Rate this response", "8")],
                         default="an essay")) as api:
        cfg["defaults"]["api_url"] = api.url
        run = multi.run(cfg, {"review": [ROW]})
    assert run.returncode == 0, run.stderr
    row = run.rows("review")[0]
    assert row["output"] == {"response": "an essay"}
    assert row["result"]["judge_score"] == 8
    assert run.summary["tasks"]["review"]["total_api_calls"] == 2


# T34: the judge call reuses the task's generation settings, model aside.
def test_judge_call_reuses_the_task_generation_settings(run_tool):
    with MockAPI(responder("8")) as api:
        run = run_tool(judge_config(api_url=api.url, scheme="rejection",
                                    temperature=0.8, n=3), [ROW],
                       args=["--max-tokens", "64"])
    assert run.returncode == 0, run.stderr
    judge = judge_calls(api)[0]
    assert judge["temperature"] == 0.8
    assert judge["max_tokens"] == 64

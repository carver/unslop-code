"""`llm_judge` evaluation: a second API call scores each response."""

from __future__ import annotations

from conftest import make_config, make_multi_config

JUDGE_MARKER = "quality evaluator"
ROW = [{"prompt_text": "describe the sea", "criteria": "vividness"}]


def judge_config(server_url, **evaluation):
    """A greedy writing task scored by an llm_judge evaluation."""
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {
            "system": f"You are a {JUDGE_MARKER}. Respond with a single integer.",
            "user": "Rate this response:\n{__response__}\n\n"
            "Criteria: {criteria}\n\nScore:",
        },
        "threshold": 7,
        "extract": "first_number",
        **evaluation,
    }
    return make_config(
        server_url,
        prompt={"system": "You are a writing assistant.", "user": "{prompt_text}"},
        evaluation=evaluation,
        output_field="response",
    )


def judge_payloads(server) -> list[dict]:
    return [
        payload
        for payload in server.payloads
        if JUDGE_MARKER in str(payload["messages"])
    ]


# Spec: "the judge request is a separate API call through the same server".
def test_judge_is_a_second_call_to_the_same_server(servers, run_cli):
    server = servers(contents=["the sea is vast"], content_if_contains={JUDGE_MARKER: "8"})
    result = run_cli(judge_config(server.url), ROW)
    assert result.exit_code == 0, result.stderr
    assert server.call_count == 2
    assert set(server.paths) == {"/v1/chat/completions"}


# Spec: "`judge_prompt` uses the same template rules as normal prompts" and
# "`__response__` is the generated response text".
def test_judge_prompt_is_rendered_with_response_and_row_fields(servers, run_cli):
    server = servers(contents=["the sea is vast"], content_if_contains={JUDGE_MARKER: "8"})
    run_cli(judge_config(server.url), ROW)
    messages = judge_payloads(server)[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == (
        "Rate this response:\nthe sea is vast\n\nCriteria: vividness\n\nScore:"
    )


# Spec: the judge example -- "if the judge returns "8", then judge_score is 8"
# and "with threshold: 7, the row passes".
def test_judge_score_and_threshold(servers, run_cli):
    server = servers(contents=["the sea is vast"], content_if_contains={JUDGE_MARKER: "8"})
    result = run_cli(judge_config(server.url), ROW)
    row = result.rows[0]
    assert row["result"]["judge_score"] == 8
    assert row["result"]["passed"] is True
    assert row["output"] == {"response": "the sea is vast"}


# Spec: "score >= threshold passes" -- a score below it fails.
def test_score_below_threshold_fails(servers, run_cli):
    server = servers(contents=["meh"], content_if_contains={JUDGE_MARKER: "4"})
    result = run_cli(judge_config(server.url), ROW)
    row = result.rows[0]
    assert row["result"]["judge_score"] == 4
    assert row["result"]["passed"] is False


# Spec: "score >= threshold passes" -- equality passes.
def test_score_equal_to_threshold_passes(servers, run_cli):
    server = servers(contents=["ok"], content_if_contains={JUDGE_MARKER: "7"})
    result = run_cli(judge_config(server.url), ROW)
    assert result.rows[0]["result"]["passed"] is True


# Spec: "extract: first_number" applied to a chatty judge reply.
def test_score_is_extracted_from_the_judge_reply(servers, run_cli):
    server = servers(contents=["ok"], content_if_contains={JUDGE_MARKER: "Score: 9/10"})
    result = run_cli(judge_config(server.url), ROW)
    assert result.rows[0]["result"]["judge_score"] == 9


# Spec: "meta includes a judge_meta object with the judge request's token
# usage, latency, model, and finish reason".
def test_judge_meta_fields(servers, run_cli):
    server = servers(
        contents=["ok"],
        content_if_contains={JUDGE_MARKER: "8"},
        prompt_tokens=45,
        completion_tokens=120,
    )
    result = run_cli(judge_config(server.url), ROW)
    judge_meta = result.rows[0]["meta"]["judge_meta"]
    assert set(judge_meta) == {
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
    }
    assert judge_meta["prompt_tokens"] == 45
    assert judge_meta["finish_reason"] == "stop"


# Spec: "if `evaluation.model` is omitted, use the task's model".
def test_judge_defaults_to_the_task_model(servers, run_cli):
    server = servers(contents=["ok"], content_if_contains={JUDGE_MARKER: "8"})
    result = run_cli(judge_config(server.url), ROW)
    assert judge_payloads(server)[0]["model"] == "gpt-4"
    assert result.rows[0]["meta"]["judge_meta"]["model"] == "gpt-4"


# Spec: "evaluation: ... model: gpt-4" -- a configured judge model is used for
# the judge call only.
def test_configured_judge_model_is_used(servers, run_cli):
    server = servers(contents=["ok"], content_if_contains={JUDGE_MARKER: "8"})
    result = run_cli(judge_config(server.url, model="judge-4"), ROW)
    assert result.exit_code == 0, result.stderr
    assert judge_payloads(server)[0]["model"] == "judge-4"
    assert result.rows[0]["meta"]["judge_meta"]["model"] == "judge-4"
    generation = [p for p in server.payloads if JUDGE_MARKER not in str(p["messages"])]
    assert generation[0]["model"] == "gpt-4"


# Spec: "judge calls count toward throughput, total_api_calls, and per-task
# API call totals".
def test_judge_calls_count_in_total_api_calls(servers, run_cli):
    server = servers(contents=["ok"], content_if_contains={JUDGE_MARKER: "8"})
    rows = [dict(ROW[0], prompt_text=f"p{i}") for i in range(3)]
    result = run_cli(judge_config(server.url), rows)
    assert result.summary["total_api_calls"] == 6
    assert result.summary["tasks"]["gsm8k_solve"]["total_api_calls"] == 6


# Spec: "judge calls count toward ... token usage totals" via the same
# summary fields as generation calls.
def test_judge_tokens_count_in_the_summary(servers, run_cli):
    server = servers(
        contents=["ok"],
        content_if_contains={JUDGE_MARKER: "8"},
        prompt_tokens=10,
        completion_tokens=5,
    )
    result = run_cli(judge_config(server.url), ROW)
    assert result.summary["total_prompt_tokens"] == 20
    assert result.summary["total_completion_tokens"] == 10


# Spec: the judge scores every rejection attempt, so `meta` carries one
# judge_meta per attempt. (T25)
def test_rejection_judges_each_attempt(servers, run_cli):
    server = servers(
        contents=["ok"], content_if_contains={JUDGE_MARKER: "3"}, workers=1
    )
    config = judge_config(server.url)
    config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 2}
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert row["result"]["attempts"] == 2
    assert [entry["judge_meta"]["model"] for entry in row["meta"]] == ["gpt-4"] * 2
    assert row["result"]["passed"] is False


# Spec: a judge reply with no number leaves nothing to compare. (T34)
def test_unscoreable_judge_reply_fails_the_row(servers, run_cli):
    server = servers(
        contents=["ok"], content_if_contains={JUDGE_MARKER: "not a score"}
    )
    result = run_cli(judge_config(server.url), ROW)
    row = result.rows[0]
    assert row["result"]["judge_score"] is None
    assert row["result"]["passed"] is False


# Spec: llm_judge extracts nothing from the generated response itself. (T22)
def test_llm_judge_reports_no_extracted_answer(servers, run_cli):
    server = servers(contents=["ok"], content_if_contains={JUDGE_MARKER: "8"})
    result = run_cli(judge_config(server.url), ROW)
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: `judge_score` and `judge_meta` belong to llm_judge rows only. (T23)
def test_non_judge_tasks_keep_the_part_1_shapes(server, run_cli):
    result = run_cli(make_config(server.url), [{"question": "q", "answer": "42"}])
    assert set(result.rows[0]["result"]) == {"passed", "extracted_answer", "attempts"}
    assert "judge_meta" not in result.rows[0]["meta"]


# Spec: the `review` task of the multi-task example, run from a multi config.
def test_judge_task_in_a_multi_task_config(servers, run_multi):
    server = servers(contents=["a response"], content_if_contains={JUDGE_MARKER: "9"})
    review = judge_config(server.url)["task"]
    for key in ("name", "api_url", "model", "rpm"):
        review.pop(key)
    config = make_multi_config(server.url, {"review": review})
    result = run_multi(config, {"review": ROW})
    assert result.exit_code == 0, result.stderr
    assert result.rows("review")[0]["result"]["judge_score"] == 9
    assert result.summary["tasks"]["review"]["total_api_calls"] == 2

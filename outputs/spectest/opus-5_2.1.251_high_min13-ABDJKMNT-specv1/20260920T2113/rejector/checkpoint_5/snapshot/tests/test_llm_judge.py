"""`llm_judge` evaluation: the judge call, its verdict, and its metadata."""

from __future__ import annotations

from copy import deepcopy

import pytest

from tests.conftest import (
    JUDGE_MARKER, SPEC_ROWS, SPEC_TASKS, judge_responder, multi_config, task_config,
)
from tests.fake_api import ok

ROW = SPEC_ROWS["review"]
JUDGE_PROMPT = SPEC_TASKS["review"]["evaluation"]["judge_prompt"]


def judge_task(server, **evaluation) -> dict:
    """A single-task config that judges its responses with the spec's judge prompt."""
    config = task_config(api_url=server.url)
    config["task"]["prompt"] = {"user": "{prompt_text}"}
    config["task"]["output_field"] = "response"
    config["task"]["evaluation"] = {
        "type": "llm_judge",
        "judge_prompt": deepcopy(JUDGE_PROMPT),
        "threshold": 7,
        "extract": "first_number",
        **evaluation,
    }
    return config


def judge_bodies(server) -> list[dict]:
    return [body for body in server.log.bodies if JUDGE_MARKER in body["messages"][0]["content"]]


# "the judge request is a separate API call through the same server"
def test_judge_is_a_second_call_to_the_same_server(cli, api):
    server = api(judge_responder("The sea is vast.", "8"))
    run = cli.run(judge_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    assert len(server.log.calls) == 2
    assert len(judge_bodies(server)) == 1
    assert {call.path for call in server.log.calls} == {"/v1/chat/completions"}


# "`judge_prompt` uses the same template rules as normal prompts"
# "`__response__` is the generated response text"
def test_judge_prompt_is_rendered_with_row_fields_and_the_response(cli, api):
    server = api(judge_responder("The sea is vast.", "8"))
    run = cli.run(judge_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    messages = judge_bodies(server)[0]["messages"]
    assert messages[0]["content"] == JUDGE_PROMPT["system"]
    user = messages[-1]["content"]
    assert "Original prompt: Describe the sea." in user
    assert "Response:\nThe sea is vast." in user
    assert "Criteria: vividness" in user
    assert "{" not in user


# "score `>= threshold` passes"
@pytest.mark.parametrize("score,passed", [("6", False), ("7", True), ("8", True), ("10", True)])
def test_threshold_decides_the_verdict(cli, api, score, passed):
    server = api(judge_responder("text", score))
    run = cli.run(judge_task(server), [ROW])
    assert run.rows[0]["result"]["passed"] is passed


# "if the judge returns `\"8\"`, then `judge_score` is `8`"
# "`result.extracted_answer` is the text `extract` took from the judge's reply"
def test_result_carries_judge_score_and_extracted_answer(cli, api):
    server = api(judge_responder("The sea is vast.", "8"))
    run = cli.run(judge_task(server), [ROW])
    result = run.rows[0]["result"]
    assert result["judge_score"] == 8
    assert result["extracted_answer"] == "8"
    assert result["passed"] is True


# "`result.extracted_answer` is the text `extract` took from the judge's reply"
# (extract runs over the judge reply, not the generated response)
def test_extracted_answer_comes_from_the_judge_reply(cli, api):
    server = api(judge_responder("I rate myself 2 out of 10", "Score: 9"))
    run = cli.run(judge_task(server), [ROW])
    assert run.rows[0]["result"]["extracted_answer"] == "9"
    assert run.rows[0]["result"]["judge_score"] == 9


# "generation response is produced first" - the kept output is the generation
def test_output_field_holds_the_generated_response(cli, api):
    server = api(judge_responder("The sea is vast.", "8"))
    run = cli.run(judge_task(server), [ROW])
    assert run.rows[0]["output"] == {"response": "The sea is vast."}


# "`meta` includes a `judge_meta` object with the judge request's token usage,
#  latency, model, and finish reason"
def test_judge_meta_records_the_judge_call(cli, api):
    def responder(index, body):
        if JUDGE_MARKER in body["messages"][0]["content"]:
            return ok("8", prompt_tokens=31, completion_tokens=1, finish_reason="length")
        return ok("The sea is vast.", prompt_tokens=7, completion_tokens=4)

    server = api(responder)
    run = cli.run(judge_task(server), [ROW])
    meta = run.rows[0]["meta"]
    judge_meta = meta["judge_meta"]
    assert judge_meta["prompt_tokens"] == 31
    assert judge_meta["completion_tokens"] == 1
    assert judge_meta["total_tokens"] == 32
    assert judge_meta["model"] == "gpt-4"
    assert judge_meta["finish_reason"] == "length"
    assert isinstance(judge_meta["latency_ms"], int)
    assert meta["prompt_tokens"] == 7  # the generation call's own metadata is unchanged


# "if `evaluation.model` is omitted, use the task's model"
def test_judge_defaults_to_the_task_model(cli, api):
    server = api(judge_responder("text", "8"))
    run = cli.run(judge_task(server), [ROW], "--model", "gpt-5")
    assert judge_bodies(server)[0]["model"] == "gpt-5"
    assert run.rows[0]["meta"]["judge_meta"]["model"] == "gpt-5"


# "evaluation: ... model: gpt-4" - an explicit judge model is used for the judge call
def test_explicit_judge_model_is_used(cli, api):
    server = api(judge_responder("text", "8"))
    run = cli.run(judge_task(server, model="judge-model"), [ROW])
    assert judge_bodies(server)[0]["model"] == "judge-model"
    assert run.rows[0]["meta"]["judge_meta"]["model"] == "judge-model"
    assert server.log.bodies[0]["model"] == "gpt-4"


# "--eval-model <string>: override the judge model for all selected `llm_judge` tasks"
def test_eval_model_flag_overrides_the_judge_model(cli, api):
    server = api(judge_responder("text", "8"))
    cli.run(judge_task(server, model="judge-model"), [ROW], "--eval-model", "judge-x")
    assert judge_bodies(server)[0]["model"] == "judge-x"


# "judge calls count toward throughput, `total_api_calls`, and per-task API
#  call totals"
def test_judge_calls_count_toward_total_api_calls(cli, api):
    server = api(judge_responder("text", "8"))
    rows = [{"prompt_text": f"p{index}", "criteria": "clarity"} for index in range(3)]
    run = cli.run(judge_task(server), rows)
    assert run.summary["total_api_calls"] == 6
    assert run.summary["throughput_rpm"] > 0


# "the judge request is a separate API call" - judge failures fail the row
def test_failed_judge_call_fails_the_row(cli, api):
    def responder(index, body):
        if JUDGE_MARKER in body["messages"][0]["content"]:
            return {"status": 500, "payload": {}}
        return ok("The sea is vast.")

    server = api(responder)
    run = cli.run(judge_task(server), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False
    assert run.rows[0]["result"]["judge_score"] is None


# "`extract`" applied to a judge reply with no number at all
def test_unscorable_judge_reply_fails_the_row(cli, api):
    server = api(judge_responder("text", "unrateable"))
    run = cli.run(judge_task(server), [ROW])
    assert run.rows[0]["result"]["passed"] is False
    assert run.rows[0]["result"]["judge_score"] is None


# "llm_judge" drives rejection sampling: attempts continue until one is scored high
def test_judge_drives_rejection(cli, api):
    scores = iter(["3", "4", "9"])

    def responder(index, body):
        if JUDGE_MARKER in body["messages"][0]["content"]:
            return ok(next(scores))
        return ok(f"draft {index}")

    server = api(responder)
    config = judge_task(server)
    config["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 4}
    run = cli.run(config, [ROW])
    result = run.rows[0]["result"]
    assert result["attempts"] == 3
    assert result["passed"] is True
    assert result["judge_score"] == 9
    # one judge_meta per judged attempt
    assert [meta["judge_meta"]["finish_reason"] for meta in run.rows[0]["meta"]] == ["stop"] * 3


# "llm_judge" inside a multi-task config, using the spec's `review` task
def test_review_task_in_a_multi_task_config(cli, api):
    server = api(judge_responder("The sea is vast.", "8"))
    config = multi_config("review", defaults={"api_url": server.url})
    run = cli.run_multi(config, {"review": [ROW]})
    assert run.returncode == 0, run.stderr
    row = run.task_rows("review")[0]
    assert row["output"] == {"response": "The sea is vast."}
    assert row["result"]["judge_score"] == 8
    assert run.summary["tasks"]["review"]["total_api_calls"] == 2

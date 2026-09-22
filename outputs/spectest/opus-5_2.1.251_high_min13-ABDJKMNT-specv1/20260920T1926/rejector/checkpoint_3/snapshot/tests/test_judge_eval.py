"""`llm_judge` evaluation: judge call, scoring, threshold, metadata, accounting."""

from __future__ import annotations

import pytest

from conftest import base_defaults, judge_task, task_rows
from fake_api import FakeAPI, Reply, always, by_system

from taskrunner.config import ConfigError, build_run_config

GENERATION_SYSTEM = "You are a writing assistant."
JUDGE_SYSTEM = "You are a quality evaluator."


def judge_document(api_url: str, **task_overrides) -> dict:
    return {
        "defaults": base_defaults(api_url),
        "tasks": {"review": judge_task(**task_overrides)},
    }


def run_review(write_yaml, write_inputs, run_args, workdir, api, rows, document, *extra):
    document["defaults"]["api_url"] = api.url
    config = write_yaml(document)
    data = write_inputs({"review": rows})
    return run_args(
        "run", "--config", str(config), "--input-dir", str(data),
        "--output", str(workdir / "results"), *extra,
    )


def replies(generation: str, judge: str):
    return by_system(
        {GENERATION_SYSTEM: Reply(content=generation), JUDGE_SYSTEM: Reply(content=judge)}
    )


ROW = {"prompt_text": "write a poem", "criteria": "clarity"}


# Spec: "the judge request is a separate API call through the same server"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
def test_judge_is_a_second_call_to_the_same_server(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=replies("a poem", "8")) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
        assert api.call_count == 2
        assert set(api.paths) == {"/v1/chat/completions"}
    assert result.returncode == 0


# Spec: "`judge_prompt` uses the same template rules as normal prompts" and
# "`__response__` is the generated response text"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
def test_judge_prompt_is_rendered_with_row_fields_and_response(
    write_yaml, write_inputs, run_args, workdir
):
    with FakeAPI(responder=replies("a lovely poem", "8")) as api:
        run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
        judge_request = [
            request for request in api.requests
            if request["messages"][0]["content"] == JUDGE_SYSTEM
        ][0]
    user = judge_request["messages"][-1]["content"]
    assert "a lovely poem" in user
    assert "Criteria: clarity" in user
    assert "{__response__}" not in user


# Spec: "if `evaluation.model` is omitted, use the task's model"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
def test_judge_model_defaults_to_the_task_model(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=replies("a poem", "8")) as api:
        run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
        assert {request["model"] for request in api.requests} == {"gpt-4"}


# Spec: "evaluation: ... model: "gpt-4""
# Context: Evaluation Additions; a configured judge model is used for the judge
# call only.
def test_configured_judge_model_is_used(write_yaml, write_inputs, run_args, workdir):
    evaluation = judge_task()["evaluation"] | {"model": "judge-model"}
    with FakeAPI(responder=replies("a poem", "8")) as api:
        run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW],
            judge_document(api.url, evaluation=evaluation),
        )
        models = {
            request["messages"][0]["content"]: request["model"] for request in api.requests
        }
    assert models == {GENERATION_SYSTEM: "gpt-4", JUDGE_SYSTEM: "judge-model"}


# Spec: "score `>= threshold` passes"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
@pytest.mark.parametrize("score,passed", [("6", False), ("7", True), ("8", True), ("10", True)])
def test_threshold_is_inclusive(write_yaml, write_inputs, run_args, workdir, score, passed):
    with FakeAPI(responder=replies("a poem", score)) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
    assert task_rows(result, "review")[0]["result"]["passed"] is passed


# Spec: "`result` includes `judge_score`, and `result.extracted_answer` is the
# text `extract` took from the judge's reply (`"8"` for a score of `8`)"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
def test_result_carries_judge_score_and_extracted_answer(
    write_yaml, write_inputs, run_args, workdir
):
    with FakeAPI(responder=replies("a poem", "Score: 8")) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
    written = task_rows(result, "review")[0]["result"]
    assert written["judge_score"] == 8
    assert written["extracted_answer"] == "8"
    assert written["passed"] is True


# Spec: "`meta` includes a `judge_meta` object with the judge request's token
# usage, latency, model, and finish reason"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
def test_meta_includes_judge_meta(write_yaml, write_inputs, run_args, workdir):
    responder = by_system(
        {
            GENERATION_SYSTEM: Reply(content="a poem", prompt_tokens=11, completion_tokens=22),
            JUDGE_SYSTEM: Reply(content="8", prompt_tokens=33, completion_tokens=44),
        }
    )
    with FakeAPI(responder=responder) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
    meta = task_rows(result, "review")[0]["meta"]
    assert meta["prompt_tokens"] == 11
    judge_meta = meta["judge_meta"]
    assert judge_meta["prompt_tokens"] == 33
    assert judge_meta["completion_tokens"] == 44
    assert judge_meta["total_tokens"] == 77
    assert judge_meta["model"] == "gpt-4"
    assert judge_meta["finish_reason"] == "stop"
    assert judge_meta["latency_ms"] >= 0


# Spec: "judge calls count toward throughput, `total_api_calls`, and per-task
# API call totals"
# Context: Evaluation Additions / `llm_judge` evaluation / Rules.
def test_judge_calls_count_toward_api_call_totals(write_yaml, write_inputs, run_args, workdir):
    rows = [ROW, ROW, ROW]
    with FakeAPI(responder=replies("a poem", "8")) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, rows, judge_document(api.url)
        )
        assert api.call_count == 6
    summary = result.summary
    assert summary["total_api_calls"] == 6
    assert summary["tasks"]["review"]["total_api_calls"] == 6
    assert summary["throughput_rpm"] > 0


# Spec: "generation response is produced first / judge prompt is rendered with
# `__response__` / if the judge returns `"8"`, then `judge_score` is `8` / with
# `threshold: 7`, the row passes / `meta.judge_meta` records the judge call
# metadata"
# Context: Examples / LLM judge example.
def test_llm_judge_example_from_the_spec(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=replies("a poem", "8")) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
    written = task_rows(result, "review")[0]
    assert written["output"] == {"response": "a poem"}
    assert written["result"]["judge_score"] == 8
    assert written["result"]["passed"] is True
    assert written["meta"]["judge_meta"]["model"] == "gpt-4"


# Spec: "make up to `n` attempts and keep the first passing response" (Part 1)
# with judge evaluation; each attempt gets its own judge call.
# Context: Evaluation Additions; see AMBIGUITIES T21.
def test_rejection_judges_each_attempt(write_yaml, write_inputs, run_args, workdir):
    task_overrides = {"generation": {"scheme": "rejection", "temperature": 0.8, "n": 3}}
    scores = iter(["3", "9"])

    def responder(index, body):
        if body["messages"][0]["content"] == JUDGE_SYSTEM:
            return Reply(content=next(scores))
        return Reply(content="a poem")

    with FakeAPI(responder=responder) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW],
            judge_document(api.url, **task_overrides),
        )
        assert api.call_count == 4
    written = task_rows(result, "review")[0]
    assert written["result"]["attempts"] == 2
    assert written["result"]["judge_score"] == 9
    assert [entry["judge_meta"]["completion_tokens"] for entry in written["meta"]] == [20, 20]


# Spec: "`extract`: first_number" applied to the judge reply.
# Context: Evaluation Additions; a judge reply with no number cannot score.
def test_unscoreable_judge_reply_fails_the_row(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=replies("a poem", "excellent")) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api, [ROW], judge_document(api.url)
        )
    written = task_rows(result, "review")[0]["result"]
    assert written["passed"] is False
    assert written["judge_score"] is None


# Spec: "`judge_prompt`" and "`threshold`" are what `llm_judge` needs.
# Context: Evaluation Additions / `llm_judge` evaluation.
@pytest.mark.parametrize("missing", ["judge_prompt", "threshold"])
def test_judge_requires_prompt_and_threshold(missing):
    task = judge_task()
    del task["evaluation"][missing]
    with pytest.raises(ConfigError):
        build_run_config(
            {"defaults": base_defaults("http://localhost:8000"), "tasks": {"review": task}}, {}
        )


# Spec: "`judge_prompt` uses the same template rules as normal prompts"
# Context: a judge placeholder naming a field no row has is an input error.
def test_missing_judge_template_field_is_an_input_error(
    write_yaml, write_inputs, run_args, workdir
):
    with FakeAPI(responder=always("a poem")) as api:
        result = run_review(
            write_yaml, write_inputs, run_args, workdir, api,
            [{"prompt_text": "write a poem"}], judge_document(api.url),
        )
        assert api.call_count == 0
    assert result.returncode == 1
    assert "criteria" in result.stderr

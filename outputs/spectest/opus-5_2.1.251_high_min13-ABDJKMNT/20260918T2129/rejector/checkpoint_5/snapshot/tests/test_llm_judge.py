"""`llm_judge` evaluation: a second API call that scores the response."""

from __future__ import annotations

from dataclasses import replace

from fake_server import FakeAPIServer, Reply, completion, system_of, user_of
from conftest import multi_config

JUDGE_SYSTEM = "You are a quality evaluator. Respond with only a single integer from 1 to 10."
JUDGE_USER = (
    "Rate the quality of this response.\n\nOriginal prompt: {prompt_text}\n\n"
    "Response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
)

REVIEW_TASK = {
    "prompt": {
        "system": "You are a writing assistant. Write a response to the given prompt.",
        "user": "{prompt_text}",
    },
    "generation": {"scheme": "greedy"},
    "evaluation": {
        "type": "llm_judge",
        "judge_prompt": {"system": JUDGE_SYSTEM, "user": JUDGE_USER},
        "threshold": 7,
        "extract": "first_number",
    },
    "output_field": "response",
}

ROW = {"prompt_text": "write about spring", "criteria": "clarity"}


def is_judge(payload) -> bool:
    return system_of(payload) == JUDGE_SYSTEM


def scored(score: str, response: str = "a fine essay", **kwargs):
    """Responder that answers judge calls with `score` and the rest with `response`."""

    def responder(payload, index):
        return Reply(completion(score if is_judge(payload) else response, **kwargs))

    return responder


def _run(write_config, write_input, run_argv, responder, evaluation=None, rows=(ROW,)):
    """Run a one-task `llm_judge` config and return the CLI result."""
    task = dict(REVIEW_TASK)
    if evaluation is not None:
        task["evaluation"] = evaluation
    with FakeAPIServer(responder) as api:
        config = write_config(multi_config(api.url, {"review": task}))
        inputs = write_input(list(rows), name="review.jsonl")
        result = run_argv("--config", config, "--input", f"review={inputs}")
        return replace(result, payloads=api.payloads)


# Spec: "the judge request is a separate API call through the same server"
def test_judge_is_a_second_call_to_the_same_server(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("8"))
    assert len(result.payloads) == 2
    assert sum(is_judge(payload) for payload in result.payloads) == 1


# Spec: "judge_prompt uses the same template rules as normal prompts" and
# "__response__ is the generated response text"
def test_judge_prompt_is_rendered_with_row_fields_and_response(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("8", response="an essay on spring"))
    judge_user = [user_of(p) for p in result.payloads if is_judge(p)][0]

    assert "Original prompt: write about spring" in judge_user
    assert "Response:\nan essay on spring" in judge_user
    assert "Criteria: clarity" in judge_user
    assert "{__response__}" not in judge_user


# Spec: "if the judge returns "8", then judge_score is 8" and "result includes
# judge_score"
def test_judge_score_is_reported_in_the_result(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("8"))
    assert result.task_rows("review")[0]["result"]["judge_score"] == 8


# Spec: "score >= threshold passes" - with "threshold: 7", a score of 8 passes
def test_score_above_threshold_passes(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("8"))
    assert result.task_rows("review")[0]["result"]["passed"] is True


# Spec: "score >= threshold passes" - equality passes
def test_score_equal_to_threshold_passes(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("7"))
    assert result.task_rows("review")[0]["result"]["passed"] is True


# Spec: "score >= threshold passes" - anything lower fails
def test_score_below_threshold_fails(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("6"))
    row = result.task_rows("review")[0]
    assert row["result"]["passed"] is False
    assert row["result"]["judge_score"] == 6


# Spec: "extract: first_number" applied to the judge response
def test_score_is_extracted_from_a_wordy_judge_reply(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("Score: 9 / 10"))
    assert result.task_rows("review")[0]["result"]["judge_score"] == 9


# Spec: the judge reply may carry no score at all, which cannot reach the
# threshold
def test_unscorable_judge_reply_fails(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("no idea"))
    row = result.task_rows("review")[0]
    assert row["result"]["passed"] is False
    assert row["result"]["judge_score"] is None


# Spec: "meta includes a judge_meta object with the judge request's token
# usage, latency, model, and finish reason"
def test_judge_meta_records_the_judge_call(write_config, write_input, run_argv):
    responder = scored("8", prompt_tokens=11, completion_tokens=3)
    result = _run(write_config, write_input, run_argv, responder)
    judge_meta = result.task_rows("review")[0]["meta"]["judge_meta"]

    assert judge_meta["prompt_tokens"] == 11
    assert judge_meta["completion_tokens"] == 3
    assert judge_meta["model"] == "gpt-4"
    assert judge_meta["finish_reason"] == "stop"
    assert isinstance(judge_meta["latency_ms"], int)


# Spec: "if evaluation.model is omitted, use the task's model"
def test_judge_defaults_to_the_task_model(write_config, write_input, run_argv):
    result = _run(write_config, write_input, run_argv, scored("8"))
    judge_models = [p["model"] for p in result.payloads if is_judge(p)]
    assert judge_models == ["gpt-4"]


# Spec: "model: gpt-4" under llm_judge - a configured judge model is used for
# the judge call only
def test_configured_judge_model_is_used(write_config, write_input, run_argv):
    evaluation = dict(REVIEW_TASK["evaluation"], model="judge-model")
    result = _run(write_config, write_input, run_argv, scored("8"), evaluation)
    by_kind = {is_judge(p): p["model"] for p in result.payloads}

    assert by_kind[True] == "judge-model"
    assert by_kind[False] == "gpt-4"


# Spec: "judge calls count toward throughput, total_api_calls, and per-task
# API call totals"
def test_judge_calls_count_toward_api_totals(write_config, write_input, run_argv):
    rows = [dict(ROW, prompt_text=f"p{i}") for i in range(3)]
    result = _run(write_config, write_input, run_argv, scored("8"), None, rows)
    summary = result.summary

    assert summary["total_api_calls"] == 6
    assert summary["tasks"]["review"]["total_api_calls"] == 6
    assert summary["throughput_rpm"] > 0


# Spec: judge evaluation drives rejection like any other evaluation - each
# attempt is judged
def test_judge_drives_rejection(write_config, write_input, run_argv):
    scores = ["3", "9"]
    judged = []

    def counting(payload, index):
        if not is_judge(payload):
            return Reply(completion("an essay"))
        judged.append(index)
        return Reply(completion(scores[min(len(judged) - 1, len(scores) - 1)]))

    task = dict(REVIEW_TASK, generation={"scheme": "rejection", "temperature": 0.7, "n": 3})
    with FakeAPIServer(counting) as api:
        config = write_config(multi_config(api.url, {"review": task}))
        inputs = write_input([ROW], name="review.jsonl")
        result = run_argv("--config", config, "--input", f"review={inputs}")
        call_count = len(api.payloads)

    row = result.task_rows("review")[0]
    assert row["result"]["attempts"] == 2
    assert row["result"]["passed"] is True
    assert call_count == 4


# Spec: "meta includes a judge_meta object" - one per generation attempt when
# a rejection row needs several
def test_judge_meta_accompanies_each_attempt(write_config, write_input, run_argv):
    judged = []

    def counting(payload, index):
        if not is_judge(payload):
            return Reply(completion("an essay"))
        judged.append(index)
        return Reply(completion("3" if len(judged) == 1 else "9"))

    task = dict(REVIEW_TASK, generation={"scheme": "rejection", "temperature": 0.7, "n": 3})
    with FakeAPIServer(counting) as api:
        config = write_config(multi_config(api.url, {"review": task}))
        inputs = write_input([ROW], name="review.jsonl")
        result = run_argv("--config", config, "--input", f"review={inputs}")

    metas = result.task_rows("review")[0]["meta"]
    assert len(metas) == 2
    assert [meta["judge_meta"] is not None for meta in metas] == [True, True]


# Spec: "judge_prompt uses the same template rules as normal prompts" - its
# row fields are required of every input row
def test_missing_judge_prompt_field_exits_1(write_config, write_input, run_argv):
    result = _run(
        write_config, write_input, run_argv, scored("8"), None, [{"prompt_text": "p"}]
    )
    assert result.returncode == 1
    assert "criteria" in result.stderr


# Spec: the llm_judge type needs a judge prompt and a threshold
def test_llm_judge_without_judge_prompt_exits_1(write_config, write_input, run_argv):
    evaluation = {"type": "llm_judge", "threshold": 7, "extract": "first_number"}
    result = _run(write_config, write_input, run_argv, scored("8"), evaluation)
    assert result.returncode == 1
    assert "judge_prompt" in result.stderr


# Spec: "score >= threshold passes" needs a threshold to compare against
def test_llm_judge_without_threshold_exits_1(write_config, write_input, run_argv):
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {"system": JUDGE_SYSTEM, "user": JUDGE_USER},
        "extract": "first_number",
    }
    result = _run(write_config, write_input, run_argv, scored("8"), evaluation)
    assert result.returncode == 1
    assert "threshold" in result.stderr

"""`llm_judge` evaluation: the judge call, its score, metadata and counting."""

import pytest

import fake_api

JUDGE_USER = "Rate: {__response__}"


def _judge(threshold=7, extract="first_number", model=None,
           judge_user=JUDGE_USER, judge_system=None, user="{prompt_text}"):
    judge_prompt = {"user": judge_user}
    if judge_system is not None:
        judge_prompt["system"] = judge_system
    ev = {"type": "llm_judge", "judge_prompt": judge_prompt,
          "threshold": threshold, "extract": extract, "answer_field": None}
    if model is not None:
        ev["model"] = model
    return {"evaluation": ev, "prompt": {"user": user, "system": None},
            "output_field": "response"}


def is_judge(rec):
    """Judge calls are the ones whose user prompt is the judge template."""
    return (rec.user_content or "").startswith("Rate:")


def scripted(gen_content, judge_content):
    """Generation calls answer `gen_content`, judge calls `judge_content`."""
    return fake_api.dispatch(is_judge, fake_api.always(judge_content),
                             fake_api.always(gen_content))


ROWS = [{"prompt_text": "write a poem", "criteria": "clarity"}]


# ---------------------------------------------------------------------------
# Spec: 'evaluation: type: "llm_judge"'
# Context: Evaluation Additions.  `llm_judge` is an accepted evaluation type.
# ---------------------------------------------------------------------------
def test_llm_judge_is_an_accepted_evaluation_type(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "the judge request is a separate API call through the same server"
# Context: llm_judge rules.  One row makes two calls, both to the same URL.
# ---------------------------------------------------------------------------
def test_judge_is_a_separate_call_to_the_same_server(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
        paths = {r.path for r in api.requests}
        assert api.call_count == 2
    assert paths == {"/v1/chat/completions"}


# ---------------------------------------------------------------------------
# Spec: "generation response is produced first / judge prompt is rendered with
#        __response__"
# Context: Examples, LLM judge.  Ordering: the generation call precedes its
# judge call.
# ---------------------------------------------------------------------------
def test_generation_call_precedes_the_judge_call(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        run_task(api, _judge(), rows=ROWS, check=0)
        kinds = [is_judge(r) for r in api.requests]
    assert kinds == [False, True]


# ---------------------------------------------------------------------------
# Spec: "`__response__` is the generated response text"
# Context: llm_judge rules.
# ---------------------------------------------------------------------------
def test_response_placeholder_is_the_generated_text(run_task):
    with fake_api.FakeAPI(scripted("MY POEM", "8")) as api:
        run_task(api, _judge(), rows=ROWS, check=0)
        judged = [r.user_content for r in api.requests if is_judge(r)]
    assert judged == ["Rate: MY POEM"]


# ---------------------------------------------------------------------------
# Spec: "`judge_prompt` uses the same template rules as normal prompts"
# Context: llm_judge rules.  Row fields are substituted in the judge prompt.
# ---------------------------------------------------------------------------
def test_judge_prompt_substitutes_row_fields(run_task):
    task = _judge(judge_user="Rate: {__response__} / {criteria} / "
                             "{prompt_text}")
    with fake_api.FakeAPI(scripted("MY POEM", "8")) as api:
        run_task(api, task, rows=ROWS, check=0)
        judged = [r.user_content for r in api.requests if is_judge(r)]
    assert judged == ["Rate: MY POEM / clarity / write a poem"]


# ---------------------------------------------------------------------------
# Spec: "`judge_prompt` uses the same template rules as normal prompts"
# Context: llm_judge rules.  A `judge_prompt.system` becomes a system message.
# ---------------------------------------------------------------------------
def test_judge_prompt_system_is_sent_as_a_system_message(run_task):
    task = _judge(judge_system="You are a quality evaluator.")
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        run_task(api, task, rows=ROWS, check=0)
        systems = [r.system_content for r in api.requests if is_judge(r)]
    assert systems == ["You are a quality evaluator."]


# ---------------------------------------------------------------------------
# Spec: "score `>= threshold` passes"
# Context: llm_judge rules.  Equal to the threshold passes.
# ---------------------------------------------------------------------------
def test_score_equal_to_threshold_passes(run_task):
    with fake_api.FakeAPI(scripted("a poem", "7")) as api:
        res = run_task(api, _judge(threshold=7), rows=ROWS, check=0)
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "score `>= threshold` passes"
# Context: llm_judge rules.  Below the threshold fails.
# ---------------------------------------------------------------------------
def test_score_below_threshold_fails(run_task):
    with fake_api.FakeAPI(scripted("a poem", "6")) as api:
        res = run_task(api, _judge(threshold=7), rows=ROWS, check=0)
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Spec: "`result` includes `judge_score`"
# Context: llm_judge rules.  Example: 'if the judge returns "8", then
# judge_score is 8'.
# ---------------------------------------------------------------------------
def test_result_includes_judge_score(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    assert res.rows[0]["result"]["judge_score"] == 8


# ---------------------------------------------------------------------------
# Spec: 'if the judge returns "8", then judge_score is 8 / with threshold: 7,
#        the row passes'
# Context: Examples, LLM judge.  The worked example end to end.
# ---------------------------------------------------------------------------
def test_llm_judge_example(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, _judge(threshold=7), rows=ROWS, check=0)
    row = res.rows[0]
    assert row["output"] == {"response": "a poem"}
    assert row["result"]["judge_score"] == 8
    assert row["result"]["passed"] is True
    assert row["meta"]["judge_meta"]["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# Spec: 'extract: "first_number"' applied to the judge response
# Context: llm_judge rules.  The score is read out of prose.
# ---------------------------------------------------------------------------
def test_judge_score_is_extracted_from_prose(run_task):
    with fake_api.FakeAPI(scripted("a poem", "Score: 9 out of 10")) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    assert res.rows[0]["result"]["judge_score"] == 9
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "score `>= threshold` passes"
# Context: llm_judge rules.  AMBIGUITIES T31 — a decimal score is compared
# numerically, not as text.
# ---------------------------------------------------------------------------
def test_decimal_judge_score_is_numeric(run_task):
    with fake_api.FakeAPI(scripted("a poem", "7.5")) as api:
        res = run_task(api, _judge(threshold=7), rows=ROWS, check=0)
    assert res.rows[0]["result"]["judge_score"] == 7.5
    assert res.rows[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "if `evaluation.model` is omitted, use the task's model"
# Context: llm_judge rules.
# ---------------------------------------------------------------------------
def test_judge_uses_the_task_model_when_eval_model_is_omitted(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        run_task(api, dict(_judge(), model="task-model"), rows=ROWS, check=0)
        models = {is_judge(r): r.body["model"] for r in api.requests}
    assert models == {False: "task-model", True: "task-model"}


# ---------------------------------------------------------------------------
# Spec: 'evaluation: ... model: "gpt-4"'
# Context: llm_judge rules.  A configured judge model is used for the judge
# call only.
# ---------------------------------------------------------------------------
def test_configured_judge_model_is_used_for_the_judge_call(run_task):
    task = dict(_judge(model="judge-model"), model="task-model")
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        run_task(api, task, rows=ROWS, check=0)
        models = {is_judge(r): r.body["model"] for r in api.requests}
    assert models == {False: "task-model", True: "judge-model"}


# ---------------------------------------------------------------------------
# Spec: "`meta` includes a `judge_meta` object with the judge request's token
#        usage, latency, model, and finish reason"
# Context: llm_judge rules.
# ---------------------------------------------------------------------------
def test_meta_includes_judge_meta(run_task):
    def responder(rec):
        if is_judge(rec):
            return 200, fake_api.completion("8", prompt_tokens=11,
                                            completion_tokens=2,
                                            finish_reason="length")
        return 200, fake_api.completion("a poem", prompt_tokens=30,
                                        completion_tokens=40)
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    judge_meta = res.rows[0]["meta"]["judge_meta"]
    assert judge_meta["prompt_tokens"] == 11
    assert judge_meta["completion_tokens"] == 2
    assert judge_meta["total_tokens"] == 13
    assert judge_meta["model"] == "gpt-4"
    assert judge_meta["finish_reason"] == "length"
    assert isinstance(judge_meta["latency_ms"], int)


# ---------------------------------------------------------------------------
# Spec: "`meta` includes a `judge_meta` object"
# Context: llm_judge rules.  The generation call's own metadata is unchanged
# alongside it.
# ---------------------------------------------------------------------------
def test_generation_meta_is_unchanged_next_to_judge_meta(run_task):
    def responder(rec):
        if is_judge(rec):
            return 200, fake_api.completion("8", prompt_tokens=11,
                                            completion_tokens=2)
        return 200, fake_api.completion("a poem", prompt_tokens=30,
                                        completion_tokens=40)
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    meta = res.rows[0]["meta"]
    assert meta["prompt_tokens"] == 30
    assert meta["completion_tokens"] == 40


# ---------------------------------------------------------------------------
# Spec: "judge calls count toward ... `total_api_calls`"
# Context: llm_judge rules.
# ---------------------------------------------------------------------------
def test_judge_calls_count_toward_total_api_calls(run_task):
    rows = [{"prompt_text": "p%d" % i, "criteria": "c"} for i in range(3)]
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, _judge(), rows=rows, check=0)
    assert res.summary["total_api_calls"] == 6


# ---------------------------------------------------------------------------
# Spec: "judge calls count toward throughput"
# Context: llm_judge rules.  throughput_rpm is computed from the call total
# that includes judge calls.
# ---------------------------------------------------------------------------
def test_judge_calls_count_toward_throughput(run_task):
    with fake_api.FakeAPI(scripted("a poem", "8"), latency=0.05) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    summary = res.summary
    expected = round(summary["total_api_calls"] /
                     summary["elapsed_seconds"] * 60, 1)
    assert summary["throughput_rpm"] == pytest.approx(expected, rel=0.05)


# ---------------------------------------------------------------------------
# Spec: "judge calls count toward ... per-task API call totals"
# Context: llm_judge rules.
# ---------------------------------------------------------------------------
def test_judge_calls_count_toward_per_task_api_calls(run_task):
    rows = [{"prompt_text": "p%d" % i, "criteria": "c"} for i in range(2)]
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, dict(_judge(), name="review"), rows=rows, check=0)
    assert res.summary["tasks"]["review"]["total_api_calls"] == 4


# ---------------------------------------------------------------------------
# Spec: "llm_judge" with rejection sampling
# Context: llm_judge rules + Part 1 rejection.  Each attempt is judged, and
# the row stops at the first attempt the judge passes.
# ---------------------------------------------------------------------------
def test_llm_judge_drives_rejection_sampling(run_task):
    task = _judge()
    task["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3}
    scores = {"Rate: draft1": ["3"], "Rate: draft2": ["9"]}

    def responder(rec):
        if is_judge(rec):
            return 200, fake_api.completion(scores[rec.user_content][0])
        return 200, fake_api.completion(
            "draft2" if rec.index > 1 else "draft1")

    with fake_api.FakeAPI(responder) as api:
        res = run_task(api, task, rows=ROWS, check=0)
    row = res.rows[0]
    assert row["result"]["attempts"] == 2
    assert row["result"]["passed"] is True
    assert row["result"]["judge_score"] == 9
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2
    # AMBIGUITIES T36: each attempt carries the judge_meta of its own judging.
    assert all("judge_meta" in m for m in row["meta"])


# ---------------------------------------------------------------------------
# Spec: "`result` includes `judge_score`"
# Context: llm_judge rules.  AMBIGUITIES T35 — a judge response with no number
# yields no score and a failed row.
# ---------------------------------------------------------------------------
def test_unparseable_judge_response_fails_the_row(run_task):
    with fake_api.FakeAPI(scripted("a poem", "excellent")) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    assert res.rows[0]["result"]["passed"] is False
    assert res.rows[0]["result"]["judge_score"] is None


# ---------------------------------------------------------------------------
# Spec: "the judge request is a separate API call through the same server"
# Context: llm_judge rules.  AMBIGUITIES T35 — a judge call that fails outright
# fails the evaluation without losing the generated output.
# ---------------------------------------------------------------------------
def test_failed_judge_call_fails_the_evaluation(run_task):
    def responder(rec):
        if is_judge(rec):
            return 500, {"error": {"message": "boom"}}
        return 200, fake_api.completion("a poem")

    with fake_api.FakeAPI(responder) as api:
        res = run_task(api, _judge(), rows=ROWS, check=0)
    row = res.rows[0]
    assert row["result"]["passed"] is False
    assert row["result"]["judge_score"] is None
    assert row["output"] == {"response": "a poem"}


# ---------------------------------------------------------------------------
# Spec: 'evaluation: type: "llm_judge" ... judge_prompt ... threshold'
# Context: llm_judge rules.  AMBIGUITIES T31 — `judge_prompt` is required.
# ---------------------------------------------------------------------------
def test_llm_judge_without_judge_prompt_is_an_error(run_task):
    task = _judge()
    task["evaluation"]["judge_prompt"] = None
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, task, rows=ROWS, check=None)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: "threshold: 7"
# Context: llm_judge rules.  AMBIGUITIES T31 — `threshold` is required.
# ---------------------------------------------------------------------------
def test_llm_judge_without_threshold_is_an_error(run_task):
    task = _judge()
    task["evaluation"]["threshold"] = None
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_task(api, task, rows=ROWS, check=None)
    assert res.returncode == 1


# ---------------------------------------------------------------------------
# Spec: 'review: ... evaluation: type: "llm_judge" ... output_field: "response"'
# Context: Configuration example.  A judge task inside a multi-task config.
# ---------------------------------------------------------------------------
def test_llm_judge_task_in_a_multi_task_config(run_multi):
    tasks = {"review": {
        "prompt": {"system": "You are a writing assistant.",
                   "user": "{prompt_text}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "llm_judge",
                       "judge_prompt": {"user": JUDGE_USER},
                       "threshold": 7, "extract": "first_number"},
        "output_field": "response",
    }}
    with fake_api.FakeAPI(scripted("a poem", "8")) as api:
        res = run_multi(api, tasks=tasks, inputs={"review": ROWS},
                        replace_tasks=True, check=0)
    assert res.task_rows("review")[0]["result"]["judge_score"] == 8
    assert res.summary["tasks"]["review"]["total_api_calls"] == 2

"""Spec section: Part 2 / Evaluation Additions (`llm_judge` evaluation)."""
from __future__ import annotations

import copy

import pytest

from conftest import JUDGE_TASK, base_config, judge_responder, multi_config
from mock_server import MockAPI, completion


def _judge_config(api_url, *, threshold=7, extract="first_number",
                  model=None, judge_user=None, **over):
    evaluation = {
        "type": "llm_judge",
        "judge_prompt": {
            "system": "You are a quality evaluator. Respond with only a single "
                      "integer from 1 to 10.",
            "user": judge_user or ("Rate this response:\n{__response__}\n\n"
                                   "Score:"),
        },
        "threshold": threshold,
        "extract": extract,
        "answer_field": None,
    }
    if model is not None:
        evaluation["model"] = model
    return base_config(api_url, evaluation=evaluation,
                       output_field="response", **over)


def _split(api):
    """(generation requests, judge requests) from a mock server."""
    gen, judge = [], []
    for req in api.requests:
        system = ""
        for m in req["messages"]:
            if m["role"] == "system":
                system = m["content"]
        (judge if "evaluator" in system.lower() else gen).append(req)
    return gen, judge


# ---------------------------------------------------------------------------
# Phrase: "`llm_judge` evaluation: judge_prompt / threshold / extract / model"
# Context: Part 2 / Evaluation Additions.  The spec's config block must load
# and evaluate a row.
# ---------------------------------------------------------------------------
def test_llm_judge_config_is_accepted(run_tool, write_config, write_input,
                                      workdir):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(multi_config(api.url,
                                        {"review": copy.deepcopy(JUDGE_TASK)}))
        data = write_input([{"prompt_text": "write a poem",
                             "criteria": "vividness"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review={data}"], output=out)
    assert res.returncode == 0, res
    assert res.rows_for("review")[0]["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Phrase: "the judge request is a separate API call through the same server"
# Context: Part 2 / Evaluation Additions.  One row produces two calls to the
# same endpoint.
# ---------------------------------------------------------------------------
def test_judge_is_a_separate_call_to_the_same_server(run_tool, write_config,
                                                     write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        gen, judge = _split(api)
        paths = set(api.paths)
    assert res.returncode == 0, res
    assert len(gen) == 1 and len(judge) == 1
    assert paths == {"/v1/chat/completions"}


# ---------------------------------------------------------------------------
# Phrase: "`judge_prompt` uses the same template rules as normal prompts"
# Context: Part 2 / Evaluation Additions.  Row fields render in the judge
# prompt, and the system message is sent as a system message.
# ---------------------------------------------------------------------------
def test_judge_prompt_renders_row_fields(run_tool, write_config, write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(
            api.url,
            judge_user="Rate:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"))
        data = write_input([{"question": "q", "criteria": "VIVIDNESS"}])
        res = run_tool(cfg, data)
        gen, judge = _split(api)
    assert res.returncode == 0, res
    user = judge[0]["messages"][-1]["content"]
    assert "Criteria: VIVIDNESS" in user


def test_judge_prompt_sends_its_own_system_message(run_tool, write_config,
                                                   write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        gen, judge = _split(api)
    assert res.returncode == 0, res
    roles = [m["role"] for m in judge[0]["messages"]]
    assert roles == ["system", "user"]
    assert "quality evaluator" in judge[0]["messages"][0]["content"]


# Context: same phrase + Part 1's missing-field rule (AMBIGUITIES T39).
def test_missing_judge_prompt_field_exits_1(run_tool, write_config,
                                            write_input):
    cfg = write_config(_judge_config(
        "http://127.0.0.1:1",
        judge_user="Rate:\n{__response__}\n\nCriteria: {criteria}"))
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert "criteria" in res.stderr


# ---------------------------------------------------------------------------
# Phrase: "`__response__` is the generated response text"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_response_placeholder_carries_the_generated_text(run_tool,
                                                         write_config,
                                                         write_input):
    with MockAPI(judge_responder(gen_text="A GENERATED ANSWER")) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        gen, judge = _split(api)
    assert res.returncode == 0, res
    assert "A GENERATED ANSWER" in judge[0]["messages"][-1]["content"]


# Context: same phrase - generation happens first, then the judge is called
# with its result ("generation response is produced first").
def test_generation_precedes_the_judge_call(run_tool, write_config,
                                            write_input):
    with MockAPI(judge_responder(gen_text="GEN")) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        first_system = api.requests[0]["messages"][0]["content"]
    assert res.returncode == 0, res
    assert "evaluator" not in first_system.lower()


# ---------------------------------------------------------------------------
# Phrase: "if `evaluation.model` is omitted, use the task's model"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_judge_defaults_to_the_task_model(run_tool, write_config, write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        gen, judge = _split(api)
    assert res.returncode == 0, res
    assert judge[0]["model"] == "gpt-4"


# Context: same phrase - an explicit `evaluation.model` wins.
def test_evaluation_model_overrides_the_task_model(run_tool, write_config,
                                                   write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url, model="judge-9000"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        gen, judge = _split(api)
    assert res.returncode == 0, res
    assert gen[0]["model"] == "gpt-4"
    assert judge[0]["model"] == "judge-9000"


# ---------------------------------------------------------------------------
# Phrase: "score `>= threshold` passes"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reply,expected", [
    ("9", True),
    ("7", True),     # equal to the threshold passes
    ("6", False),
    ("1", False),
    ("10", True),
])
def test_threshold_comparison(run_tool, write_config, write_input, reply,
                              expected):
    with MockAPI(judge_responder(judge_text=reply)) as api:
        cfg = write_config(_judge_config(api.url, threshold=7))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["passed"] is expected


# ---------------------------------------------------------------------------
# Phrase: "if the judge returns `"8"`, then `judge_score` is `8`" /
#         "`result` includes `judge_score`, and `result.extracted_answer` is
#          the text `extract` took from the judge's reply (`"8"` for a score of
#          `8`)"
# Context: Part 2 / Examples (LLM judge example).
# ---------------------------------------------------------------------------
def test_judge_score_and_extracted_answer(run_tool, write_config, write_input):
    with MockAPI(judge_responder(judge_text="8")) as api:
        cfg = write_config(_judge_config(api.url, threshold=7))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    result = res.rows[0]["result"]
    assert result["judge_score"] == 8
    assert result["extracted_answer"] == "8"
    assert result["passed"] is True


# Context: same phrase - `judge_score` is numeric, `extracted_answer` is text
# (AMBIGUITIES T25).
def test_judge_score_is_a_number_not_a_string(run_tool, write_config,
                                              write_input):
    with MockAPI(judge_responder(judge_text="The score is 8 out of 10")) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    result = res.rows[0]["result"]
    assert result["judge_score"] == 8
    assert not isinstance(result["judge_score"], str)
    assert result["extracted_answer"] == "8"


# Context: same phrase - a decimal judge reply keeps its fractional part.
def test_judge_score_accepts_a_decimal(run_tool, write_config, write_input):
    with MockAPI(judge_responder(judge_text="7.5")) as api:
        cfg = write_config(_judge_config(api.url, threshold=7))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    result = res.rows[0]["result"]
    assert result["judge_score"] == pytest.approx(7.5)
    assert result["extracted_answer"] == "7.5"
    assert result["passed"] is True


# Context: same phrase - an unscoreable judge reply fails the row
# (AMBIGUITIES T25).
def test_unscoreable_judge_reply_fails_the_row(run_tool, write_config,
                                               write_input):
    with MockAPI(judge_responder(judge_text="I cannot rate this")) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    result = res.rows[0]["result"]
    assert result["passed"] is False
    assert result["judge_score"] is None


# ---------------------------------------------------------------------------
# Phrase: "`meta` includes a `judge_meta` object with the judge request's token
#          usage, latency, model, and finish reason"
# Context: Part 2 / Evaluation Additions (AMBIGUITIES T24).
# ---------------------------------------------------------------------------
def test_judge_meta_fields(run_tool, write_config, write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url, model="judge-9000"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    meta = res.rows[0]["meta"]
    judge_meta = meta["judge_meta"]
    assert judge_meta["model"] == "judge-9000"
    assert judge_meta["prompt_tokens"] == 11
    assert judge_meta["completion_tokens"] == 2
    assert judge_meta["total_tokens"] == 13
    assert judge_meta["finish_reason"] == "length"
    assert isinstance(judge_meta["latency_ms"], int)


# Context: same phrase - the generation metadata is untouched beside it.
def test_generation_meta_survives_alongside_judge_meta(run_tool, write_config,
                                                       write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    meta = res.rows[0]["meta"]
    assert meta["model"] == "gpt-4"
    assert meta["prompt_tokens"] == 45
    assert meta["completion_tokens"] == 120
    assert meta["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Phrase: "judge calls count toward throughput, `total_api_calls`, and
#          per-task API call totals"
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_judge_calls_count_in_total_api_calls(run_tool, write_config,
                                              write_input):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(_judge_config(api.url))
        data = write_input([{"question": "q1"}, {"question": "q2"},
                            {"question": "q3"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 6
    assert res.summary["total_api_calls"] == 6


def test_judge_calls_count_in_per_task_totals(run_tool, write_config,
                                              write_input, workdir):
    with MockAPI(judge_responder()) as api:
        cfg = write_config(multi_config(api.url,
                                        {"review": copy.deepcopy(JUDGE_TASK)}))
        data = write_input([{"prompt_text": "p1", "criteria": "c"},
                            {"prompt_text": "p2", "criteria": "c"}])
        out = str(workdir / "results")
        res = run_tool(cfg, [f"review={data}"], output=out)
    assert res.returncode == 0, res
    assert res.summary["tasks"]["review"]["total_api_calls"] == 4


# ---------------------------------------------------------------------------
# Phrase: "`llm_judge`" combined with Part 1's rejection scheme
# Context: Part 2.  Each rejection attempt is judged; sampling stops at the
# first attempt the judge passes.
# ---------------------------------------------------------------------------
def test_judge_drives_rejection_sampling(run_tool, write_config, write_input):
    responder = judge_responder(
        gen_text="unused",
        judge_by_response={"GOOD": "9", "BAD": "2"})

    calls = {"n": 0}

    def gen_then_judge(req, i):
        system = req["messages"][0]["content"]
        if "evaluator" in system.lower():
            return responder(req, i)
        calls["n"] += 1
        text = "BAD" if calls["n"] < 3 else "GOOD"
        return 200, completion(text)

    with MockAPI(gen_then_judge) as api:
        cfg = write_config(_judge_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 4}))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
        total = api.call_count
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"response": "GOOD"}
    assert total == 6          # 3 generations + 3 judge calls


# Context: same phrase - with several attempts `meta` is a list and each entry
# carries its own `judge_meta` (AMBIGUITIES T24).
def test_each_rejection_attempt_has_its_own_judge_meta(run_tool, write_config,
                                                       write_input):
    calls = {"n": 0}

    def gen_then_judge(req, i):
        system = req["messages"][0]["content"]
        if "evaluator" in system.lower():
            user = req["messages"][-1]["content"]
            score = "9" if "GOOD" in user else "2"
            return 200, completion(score, prompt_tokens=11,
                                   completion_tokens=2,
                                   finish_reason="length")
        calls["n"] += 1
        return 200, completion("BAD" if calls["n"] < 2 else "GOOD")

    with MockAPI(gen_then_judge) as api:
        cfg = write_config(_judge_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    meta = res.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 2
    assert all("judge_meta" in m for m in meta)
    assert [m["judge_meta"]["completion_tokens"] for m in meta] == [2, 2]


# ---------------------------------------------------------------------------
# Phrase: "`threshold`" / "`judge_prompt`" are required for `llm_judge`
# Context: Part 2 / Evaluation Additions.
# ---------------------------------------------------------------------------
def test_llm_judge_without_judge_prompt_exits_1(run_tool, write_config,
                                                write_input):
    cfg = write_config(base_config(
        "http://127.0.0.1:1",
        evaluation={"type": "llm_judge", "threshold": 7, "answer_field": None,
                    "extract": "first_number"}))
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


def test_llm_judge_without_threshold_exits_1(run_tool, write_config,
                                             write_input):
    cfg_dict = _judge_config("http://127.0.0.1:1")
    del cfg_dict["task"]["evaluation"]["threshold"]
    cfg = write_config(cfg_dict)
    data = write_input([{"question": "q"}])
    res = run_tool(cfg, data)
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: "`extract`" applied to the judge's reply, not the response
# Context: Part 2 / Evaluation Additions.  The `extract` method configured on
# an `llm_judge` evaluation reads the judge's text.
# ---------------------------------------------------------------------------
def test_extract_reads_the_judge_reply_not_the_response(run_tool, write_config,
                                                        write_input):
    with MockAPI(judge_responder(gen_text="my answer is 42",
                                 judge_text="score: 9")) as api:
        cfg = write_config(_judge_config(api.url, extract="first_number"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "9"


# Context: same phrase - `last_number` also works on the judge's reply.
def test_judge_extract_can_be_last_number(run_tool, write_config, write_input):
    with MockAPI(judge_responder(judge_text="out of 10, I give 9")) as api:
        cfg = write_config(_judge_config(api.url, extract="last_number"))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] == "9"
    assert res.rows[0]["result"]["judge_score"] == 9

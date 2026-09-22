"""Wire format: endpoint, request body, response parsing, retries."""

import pytest

import fake_api


# ---------------------------------------------------------------------------
# Spec: "Send POST requests to {api_url}/v1/chat/completions"
# Context: API Contract.  The path is appended to the configured api_url.
# ---------------------------------------------------------------------------
def test_requests_go_to_chat_completions_path(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, check=0)
        assert api.requests[0].path == "/v1/chat/completions"


# ---------------------------------------------------------------------------
# Spec: "{api_url}/v1/chat/completions"
# Context: API Contract.  A trailing slash on api_url must not double up.
# ---------------------------------------------------------------------------
def test_trailing_slash_in_api_url_is_handled(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, api_url=api.url + "/", check=0)
        assert api.requests[0].path == "/v1/chat/completions"


# ---------------------------------------------------------------------------
# Spec: request body {"model", "messages", "temperature", "max_tokens"}
# Context: API Contract.  Exactly the documented shape, with system first and
# user second.
# ---------------------------------------------------------------------------
def test_request_body_matches_documented_shape(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api,
                 task={"model": "gpt-4",
                       "prompt": {"system": "SYS", "user": "{question}"},
                       "generation": {"scheme": "greedy", "max_tokens": 512}},
                 rows=[{"question": "What is 2 + 3?", "answer": "5"}], check=0)
        body = api.bodies()[0]
    assert body["model"] == "gpt-4"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "What is 2 + 3?"},
    ]


# ---------------------------------------------------------------------------
# Spec: the request body lists model/messages/temperature/max_tokens only.
# Context: API Contract.  `n` is a client-side attempt count, not a wire field.
# ---------------------------------------------------------------------------
def test_n_is_not_sent_in_request_body(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 999")) as api:
        run_task(api, task={"generation": {"scheme": "rejection",
                                           "temperature": 0.8, "n": 2}},
                 check=0)
        assert "n" not in api.bodies()[0]


# ---------------------------------------------------------------------------
# Spec: "POST"
# Context: API Contract.  Requests carry a JSON body over POST; the fake
# server only implements do_POST, so a non-POST verb would fail the run.
# ---------------------------------------------------------------------------
def test_requests_use_post_with_json_body(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, check=0)
        assert "__raw__" not in api.bodies()[0]


# ---------------------------------------------------------------------------
# Spec: the documented response shape (choices[0].message.content)
# Context: API Contract.  Content is taken from the first choice's message.
# ---------------------------------------------------------------------------
def test_response_content_is_read_from_first_choice(run_task):
    with fake_api.FakeAPI(fake_api.always("...response text...")) as api:
        res = run_task(api, task={"evaluation": None},
                       rows=[{"question": "q"}], check=0)
    assert res.rows[0]["output"]["solution"] == "...response text..."


# ---------------------------------------------------------------------------
# Spec: response "usage": {prompt_tokens, completion_tokens, total_tokens}
#       and "finish_reason"
# Context: API Contract -> meta.
# ---------------------------------------------------------------------------
def test_usage_and_finish_reason_are_surfaced_in_meta(run_task):
    responder = fake_api.always("#### 5", prompt_tokens=45,
                                completion_tokens=120, finish_reason="length")
    with fake_api.FakeAPI(responder) as api:
        res = run_task(api, check=0)
    meta = res.rows[0]["meta"]
    assert meta["prompt_tokens"] == 45
    assert meta["completion_tokens"] == 120
    assert meta["total_tokens"] == 165
    assert meta["finish_reason"] == "length"


# ---------------------------------------------------------------------------
# Spec: "If a request receives an HTTP 5xx, retry it up to 3 times."
# Context: API Contract.  A transient 5xx is retried and the row then succeeds.
# ---------------------------------------------------------------------------
def test_transient_5xx_is_retried_and_row_succeeds(run_task):
    with fake_api.FakeAPI(fake_api.fail_times(2, "#### 5")) as api:
        res = run_task(api, check=0)
        assert api.call_count == 3
    row = res.rows[0]
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"]["passed"] is True


# ---------------------------------------------------------------------------
# Spec: "Retry requests count toward total_api_calls, but for greedy and
#        sample rows they do not increase the logical result.attempts count."
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_retries_count_as_api_calls_but_not_attempts(run_task):
    with fake_api.FakeAPI(fake_api.fail_times(2, "#### 5")) as api:
        res = run_task(api, check=0)
    assert res.rows[0]["result"]["attempts"] == 1
    assert res.summary["total_api_calls"] == 3


# ---------------------------------------------------------------------------
# Spec: "retry it up to 3 times. After the third failure, treat that row as
#        failed" (AMBIGUITIES T1 — 3 HTTP calls in total per logical attempt)
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_persistent_5xx_gives_up_after_three_calls(run_task):
    with fake_api.FakeAPI(fake_api.sequence([500])) as api:
        res = run_task(api, check=0)
        assert api.call_count == 3
    assert res.summary["total_api_calls"] == 3


# ---------------------------------------------------------------------------
# Spec: "After the third failure, treat that row as failed, emit null output
#        for it, count it as failed in the summary, and continue."
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_exhausted_retries_emit_null_output_and_count_failed(run_task):
    with fake_api.FakeAPI(fake_api.sequence([500])) as api:
        res = run_task(api, check=0)
    row = res.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert res.summary["failed"] == 1
    assert res.summary["passed"] == 0


# ---------------------------------------------------------------------------
# Spec: "... and continue."
# Context: API Contract.  One dead row does not abort the run: the other rows
# are still processed and the exit code is 0.
# ---------------------------------------------------------------------------
def test_failed_row_does_not_abort_the_run(run_task):
    script = {"bad": [500, 500, 500], "good": ["#### 5"]}
    with fake_api.FakeAPI(fake_api.per_prompt(script)) as api:
        res = run_task(api, task={"prompt": {"system": "s", "user": "{question}"}},
                       rows=[{"question": "bad", "answer": "5"},
                             {"question": "good", "answer": "5"}], check=0)
    assert res.rows[0]["output"] is None
    assert res.rows[1]["output"] == {"solution": "#### 5"}
    assert res.summary["total"] == 2
    assert res.summary["passed"] == 1
    assert res.summary["failed"] == 1


# ---------------------------------------------------------------------------
# Spec: "If a request receives an HTTP 5xx, retry it up to 3 times."
# Context: AMBIGUITIES T23 — only 5xx is retried; a 4xx fails the row after a
# single call, and the run still exits 0.
# ---------------------------------------------------------------------------
def test_4xx_is_not_retried(run_task):
    with fake_api.FakeAPI(fake_api.sequence([400])) as api:
        res = run_task(api, check=0)
        assert api.call_count == 1
    assert res.rows[0]["output"] is None
    assert res.summary["total_api_calls"] == 1


# ---------------------------------------------------------------------------
# Spec: "count it as failed in the summary" (AMBIGUITIES T3)
# Context: API Contract.  A row with no successful response still carries a
# meta entry; its token fields and finish_reason are null.
# ---------------------------------------------------------------------------
def test_failed_row_meta_has_null_tokens(run_task):
    with fake_api.FakeAPI(fake_api.sequence([500])) as api:
        res = run_task(api, check=0)
    meta = res.rows[0]["meta"]
    assert meta["prompt_tokens"] is None
    assert meta["completion_tokens"] is None
    assert meta["finish_reason"] is None
    assert meta["model"] == "gpt-4"

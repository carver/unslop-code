"""Spec section: API Contract (request shape, endpoint, retries)."""
from __future__ import annotations

from conftest import base_config
from mock_server import MockAPI, always, completion, sequence


# ---------------------------------------------------------------------------
# Phrase: "Send POST requests to {api_url}/v1/chat/completions"
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_endpoint_path(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        paths = api.paths
    assert res.returncode == 0, res
    assert paths == ["/v1/chat/completions"]


# Context: same phrase - a trailing slash on api_url must not double up.
def test_endpoint_path_with_trailing_slash_api_url(run_tool, write_config,
                                                   write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url + "/"))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        paths = api.paths
    assert res.returncode == 0, res
    assert paths == ["/v1/chat/completions"]


# ---------------------------------------------------------------------------
# Phrase: the request body block
#   {"model", "messages": [system, user], "temperature", "max_tokens"}
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_request_body_shape(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["model"] == "gpt-4"
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == 512
    assert sent["messages"] == [
        {"role": "system",
         "content": "Solve the math problem. Put your final answer after ####."},
        {"role": "user", "content": "What is 2 + 3?"},
    ]


# ---------------------------------------------------------------------------
# Phrase: "The API returns standard OpenAI-style chat completions" with
#         choices[0].message.content, finish_reason and usage.
# Context: API Contract.  The response fields flow into `output` and `meta`.
# ---------------------------------------------------------------------------
def test_response_fields_are_consumed(run_tool, write_config, write_input):
    body = completion("...response text...", prompt_tokens=45,
                      completion_tokens=120, finish_reason="length")
    with MockAPI(lambda req, i: (200, body)) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] == {"solution": "...response text..."}
    assert row["meta"]["prompt_tokens"] == 45
    assert row["meta"]["completion_tokens"] == 120
    assert row["meta"]["total_tokens"] == 165
    assert row["meta"]["finish_reason"] == "length"


# ---------------------------------------------------------------------------
# Phrase: "If a request receives an HTTP 5xx, retry it up to 3 total requests."
# Context: API Contract.  Two failures then a success = 3 calls, row succeeds.
# ---------------------------------------------------------------------------
def test_retries_after_5xx_then_succeeds(run_tool, write_config, write_input):
    responder = sequence([
        (500, {"error": "boom"}),
        (503, {"error": "boom"}),
        "#### 5",
    ])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3
    assert res.rows[0]["result"]["passed"] is True


# Context: same phrase - a request is never sent more than 3 times in total.
def test_no_more_than_three_total_requests(run_tool, write_config, write_input):
    with MockAPI(lambda req, i: (500, {"error": "boom"})) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 3


# ---------------------------------------------------------------------------
# Phrase: "After the third failure, treat that row as failed, emit null output
#          for it, count it as failed in the summary, and continue."
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_row_fails_after_exhausted_retries_and_run_continues(
        run_tool, write_config, write_input):
    def responder(req, i):
        user = req["messages"][-1]["content"]
        if user == "bad":
            return 500, {"error": "boom"}
        return 200, completion("#### 5")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "bad", "answer": "5"},
                            {"question": "good", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    rows = res.rows
    assert rows[0]["output"] is None
    assert rows[1]["output"] == {"solution": "#### 5"}
    summary = res.summary
    assert summary["total"] == 2
    assert summary["failed"] == 1
    assert summary["passed"] == 1


# ---------------------------------------------------------------------------
# Phrase: "Retry requests count toward total_api_calls, but for greedy and
#          sample rows they do not increase the logical result.attempts count."
# Context: API Contract.
# ---------------------------------------------------------------------------
def test_retries_count_in_api_calls_not_in_attempts(run_tool, write_config,
                                                    write_input):
    responder = sequence([(500, {"e": 1}), (500, {"e": 1}), "#### 5"])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["attempts"] == 1
    assert res.summary["total_api_calls"] == 3


# Context (ambiguity T1): a row whose retries are exhausted reports meta as null.
def test_meta_for_exhausted_row(run_tool, write_config, write_input):
    with MockAPI(lambda req, i: (500, {"e": 1})) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["meta"] is None
    assert row["result"]["attempts"] == 1
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["passed"] is False


# Context (ambiguity T9): a 4xx is not retried.
def test_4xx_is_not_retried(run_tool, write_config, write_input):
    with MockAPI(lambda req, i: (400, {"error": "bad request"})) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 1
    assert res.rows[0]["output"] is None
    assert res.summary["failed"] == 1


# Context: "It does not return rate-limit errors." - the run is still an
# ordinary success when every row answers on the first try.
def test_no_rate_limit_handling_needed(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.01) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"}
                            for i in range(20)])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 0, res
    assert calls == 20
    assert res.summary["passed"] == 20

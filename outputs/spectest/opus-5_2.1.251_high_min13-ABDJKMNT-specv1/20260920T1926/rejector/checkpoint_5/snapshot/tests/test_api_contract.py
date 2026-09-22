"""HTTP request shape, response parsing and the 5xx retry policy."""

from __future__ import annotations

from conftest import base_task
from fake_api import FakeAPI, Reply, always, sequence


# Spec: "Send POST requests to {api_url}/v1/chat/completions"
# Context: API Contract.
def test_requests_go_to_chat_completions_path(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, data)
        assert api.paths == ["/v1/chat/completions"]


# Spec: request body {"model", "messages": [system, user], "temperature",
# "max_tokens"}.
# Context: API Contract.
def test_request_body_shape(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "greedy", "max_tokens": 256}
        config = write_config(task)
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        run_cli(config, data)
        body = api.requests[0]
    assert body == {
        "model": "gpt-4",
        "messages": [
            {
                "role": "system",
                "content": "Solve the math problem. Put your final answer after ####.",
            },
            {"role": "user", "content": "What is 2 + 3?"},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
    }


# Spec: "greedy: force temperature to 0.0; n is ignored"
# Context: Generation behavior; n never appears in the request body.
def test_greedy_sends_zero_temperature_and_no_n(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "greedy", "temperature": 0.9, "n": 4}
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, data)
        assert api.requests[0]["temperature"] == 0.0
        assert "n" not in api.requests[0]
        assert api.call_count == 1


# Spec: "sample: temperature must be > 0; n is ignored"
# Context: Generation behavior.
def test_sample_sends_configured_temperature_once(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url)
        task["generation"] = {"scheme": "sample", "temperature": 0.7, "n": 4}
        config = write_config(task)
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(config, data)
        assert api.requests[0]["temperature"] == 0.7
        assert api.call_count == 1


# Spec: response "choices[0].message.content", "finish_reason", "usage".
# Context: API Contract; parsed straight into output and meta.
def test_response_fields_are_parsed_into_the_row(write_config, write_input, run_cli):
    reply = Reply(content="2 + 3 = 5\n#### 5", finish_reason="length",
                  prompt_tokens=45, completion_tokens=120)
    with FakeAPI(responder=sequence([reply])) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    row = result.rows[0]
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["meta"]["finish_reason"] == "length"
    assert row["meta"]["prompt_tokens"] == 45
    assert row["meta"]["completion_tokens"] == 120
    assert row["meta"]["total_tokens"] == 165


# Spec: "If a request receives an HTTP 5xx, retry it up to 3 total requests."
# Context: API Contract.
def test_two_failures_then_success_uses_three_calls(write_config, write_input, run_cli):
    script = [Reply(status=500), Reply(status=503), Reply(content="#### 5")]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 3
    row = result.rows[0]
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"]["passed"] is True


# Spec: "Retry requests count toward total_api_calls, but for greedy and sample
# rows they do not increase the logical result.attempts count."
# Context: API Contract.
def test_retries_count_as_api_calls_not_attempts(write_config, write_input, run_cli):
    script = [Reply(status=500), Reply(content="#### 5")]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert result.rows[0]["result"]["attempts"] == 1
    assert result.summary["total_api_calls"] == 2


# Spec: "After the third failure, treat that row as failed, emit null output
# for it, count it as failed in the summary, and continue."
# Context: API Contract.
def test_three_failures_fail_the_row(write_config, write_input, run_cli):
    with FakeAPI(responder=always("", status=500)) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 3
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["extracted_answer"] is None
    assert result.summary["failed"] == 1
    assert result.summary["total_api_calls"] == 3
    assert result.returncode == 0


# Spec: "...and continue."
# Context: API Contract; a failed row must not abort the remaining rows.
def test_failed_row_does_not_stop_other_rows(write_config, write_input, run_cli):
    def responder(index, body):
        if body["messages"][-1]["content"] == "bad":
            return Reply(status=500)
        return Reply(content="#### 5")

    with FakeAPI(responder=responder) as api:
        config = write_config(base_task(api.url))
        data = write_input(
            [
                {"question": "bad", "answer": "5"},
                {"question": "good", "answer": "5"},
            ]
        )
        result = run_cli(config, data)
    rows = result.rows
    assert rows[0]["output"] is None
    assert rows[1]["output"] == {"solution": "#### 5"}
    assert result.summary == {
        **result.summary,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "total_api_calls": 4,
    }


# Spec: 5xx is the retried condition (see AMBIGUITIES T15 for 4xx).
# Context: API Contract.
def test_client_error_is_not_retried(write_config, write_input, run_cli):
    with FakeAPI(responder=always("", status=400)) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 1
    assert result.rows[0]["output"] is None
    assert result.summary["failed"] == 1


# Spec: "If a request receives an HTTP 5xx, retry it up to 3 total requests."
# Context: API Contract; the budget is per request, so each row retries alone.
def test_retry_budget_is_per_row(write_config, write_input, run_cli):
    with FakeAPI(responder=always("", status=500)) as api:
        config = write_config(base_task(api.url))
        data = write_input([{"question": f"q{i}", "answer": "5"} for i in range(3)])
        result = run_cli(config, data)
        assert api.call_count == 9
    assert result.summary["failed"] == 3

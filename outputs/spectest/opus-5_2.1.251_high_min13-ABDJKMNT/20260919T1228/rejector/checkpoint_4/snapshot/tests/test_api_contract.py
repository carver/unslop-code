"""Request shape, endpoint, response parsing, and 5xx retry behaviour."""

from __future__ import annotations

from conftest import make_config

ROW = [{"question": "What is 2 + 3?", "answer": "42"}]


# Spec: "Send POST requests to {api_url}/v1/chat/completions".
def test_requests_go_to_the_chat_completions_path(server, run_cli):
    run_cli(make_config(server.url), ROW)
    assert server.paths == ["/v1/chat/completions"]


# Spec: the request body carries "model", "messages", "temperature",
# "max_tokens".
def test_request_body_shape(server, run_cli):
    config = make_config(
        server.url, generation={"scheme": "greedy", "max_tokens": 256}
    )
    run_cli(config, ROW)
    payload = server.payloads[0]
    assert payload == {
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


# Spec: messages are the rendered system prompt then the rendered user prompt.
def test_messages_are_system_then_user(server, run_cli):
    run_cli(make_config(server.url), ROW)
    roles = [message["role"] for message in server.payloads[0]["messages"]]
    assert roles == ["system", "user"]


# Spec: "The API returns standard OpenAI-style chat completions" -- the
# response content becomes the row output and usage/finish_reason become meta.
def test_response_fields_are_consumed(servers, run_cli):
    server = servers(contents=["2 + 3 = 5\n#### 5"], prompt_tokens=30, completion_tokens=10)
    config = make_config(server.url)
    result = run_cli(config, [{"question": "What is 2 + 3?", "answer": "5"}])
    row = result.rows[0]
    assert row["output"]["solution"] == "2 + 3 = 5\n#### 5"
    assert row["meta"]["prompt_tokens"] == 30
    assert row["meta"]["completion_tokens"] == 10
    assert row["meta"]["total_tokens"] == 40
    assert row["meta"]["finish_reason"] == "stop"


# Spec: "If a request receives an HTTP 5xx, retry it up to 3 times" -- a
# transient failure is retried and the row still succeeds.
def test_transient_5xx_is_retried_and_row_succeeds(servers, run_cli):
    server = servers(contents=["#### 42"], fail_calls={0, 1})
    result = run_cli(make_config(server.url), ROW)
    assert result.exit_code == 0
    assert result.rows[0]["output"]["solution"] == "#### 42"
    assert server.call_count == 3


# Spec: "retry it up to 3 times. After the third failure, treat that row as
# failed, emit null output for it". (T1: 1 initial call + 3 retries.)
def test_retries_are_bounded(servers, run_cli):
    server = servers(fail_calls=set(range(50)))
    result = run_cli(make_config(server.url), ROW)
    assert result.exit_code == 0
    assert server.call_count == 4
    assert result.rows[0]["output"] is None


# Spec: "Retry requests count toward total_api_calls".
def test_retries_count_toward_total_api_calls(servers, run_cli):
    server = servers(contents=["#### 42"], fail_calls={0})
    result = run_cli(make_config(server.url), ROW)
    assert result.summary["total_api_calls"] == 2


# Spec: "for greedy and sample rows they [retries] do not increase the logical
# result.attempts count".
def test_retries_do_not_increase_attempts(servers, run_cli):
    server = servers(contents=["#### 42"], fail_calls={0, 1})
    result = run_cli(make_config(server.url), ROW)
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "treat that row as failed ... count it as failed in the summary, and
# continue" -- other rows are still processed.
def test_run_continues_after_a_failed_row(servers, run_cli):
    # Every request for the first row fails; the second row is unaffected.
    server = servers(contents=["#### 42"], fail_if_contains="q1")
    rows = [{"question": "q1", "answer": "42"}, {"question": "q2", "answer": "42"}]
    result = run_cli(make_config(server.url), rows)
    outputs = [row["output"] for row in result.rows]
    assert outputs[0] is None
    assert outputs[1] == {"solution": "#### 42"}
    assert result.summary["failed"] == 1
    assert result.summary["passed"] == 1

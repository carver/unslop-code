"""Request shape, response parsing, and 5xx retry behaviour."""

from __future__ import annotations

from tests.conftest import task_config
from tests.fake_api import error, ok

ROW = {"question": "What is 2 + 3?", "answer": "5"}


# "Send POST requests to {api_url}/v1/chat/completions"
def test_requests_go_to_chat_completions_path(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert [call.path for call in server.log.calls] == ["/v1/chat/completions"]


# '{"model": "<model>", "messages": [...], "temperature": 0.0,
#   "max_tokens": 512}'
def test_request_body_shape(cli, static_api):
    server = static_api("#### 5")
    config = task_config(
        api_url=server.url,
        generation={"scheme": "greedy", "max_tokens": 512},
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    assert server.log.bodies[0] == {
        "model": "gpt-4",
        "messages": [
            {"role": "system", "content": "Solve the math problem. Final answer after ####."},
            {"role": "user", "content": "What is 2 + 3?"},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }


# "greedy: force temperature to 0.0"
def test_greedy_sends_zero_temperature(cli, static_api):
    server = static_api("#### 5")
    config = task_config(api_url=server.url, generation={"scheme": "greedy", "temperature": 0.9})
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    assert server.log.bodies[0]["temperature"] == 0.0


# "sample: temperature must be > 0" - the configured temperature is sent
def test_sample_sends_configured_temperature(cli, static_api):
    server = static_api("#### 5")
    config = task_config(api_url=server.url, generation={"scheme": "sample", "temperature": 0.7})
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    assert server.log.bodies[0]["temperature"] == 0.7


# "The API returns standard OpenAI-style chat completions" - content, usage and
# finish_reason are carried into the output row
def test_response_fields_are_carried_into_the_row(cli, api):
    server = api(lambda index, body: ok(
        "2 + 3 = 5\n#### 5", prompt_tokens=45, completion_tokens=120, finish_reason="length",
    ))
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["meta"]["prompt_tokens"] == 45
    assert row["meta"]["completion_tokens"] == 120
    assert row["meta"]["total_tokens"] == 165
    assert row["meta"]["finish_reason"] == "length"


# "If a request receives an HTTP 5xx, retry it up to 3 total requests."
def test_fifth_hundred_is_retried_until_success(cli, api):
    def responder(index, body):
        return error(503) if index < 2 else ok("#### 5")

    server = api(responder)
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert len(server.log.calls) == 3
    assert run.rows[0]["output"] == {"solution": "#### 5"}


# "Retry requests count toward total_api_calls, but for greedy and sample rows
#  they do not increase the logical result.attempts count."
def test_retries_count_as_api_calls_not_attempts(cli, api):
    def responder(index, body):
        return error(500) if index < 2 else ok("#### 5")

    server = api(responder)
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert run.rows[0]["result"]["attempts"] == 1
    assert run.summary["total_api_calls"] == 3


# "After the third failure, treat that row as failed, emit null output for it,
#  count it as failed in the summary, and continue."
def test_exhausted_retries_fail_the_row_and_continue(cli, api):
    def responder(index, body):
        # Every request for the first row's prompt fails; the second row is fine.
        return error(500) if body["messages"][-1]["content"] == "bad" else ok("#### 5")

    server = api(responder)
    rows = [{"question": "bad", "answer": "5"}, {"question": "good", "answer": "5"}]
    run = cli.run(task_config(api_url=server.url), rows)
    assert run.returncode == 0
    assert run.rows[0]["output"] is None
    assert run.rows[0]["result"]["passed"] is False
    assert run.rows[1]["output"] == {"solution": "#### 5"}
    assert run.summary == {**run.summary, "total": 2, "passed": 1, "failed": 1}
    assert run.summary["total_api_calls"] == 4  # 3 failed + 1 success


# "If a request receives an HTTP 5xx, retry it up to 3 total requests"
# (T13: a 4xx is deterministic and is not retried)
def test_four_hundred_is_not_retried(cli, api):
    server = api(lambda index, body: error(400, "bad request"))
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert len(server.log.calls) == 1
    assert run.rows[0]["output"] is None
    assert run.summary["failed"] == 1

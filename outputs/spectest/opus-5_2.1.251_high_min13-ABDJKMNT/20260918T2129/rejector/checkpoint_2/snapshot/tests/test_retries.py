"""HTTP 5xx retry policy and failed-row handling."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, completion
from conftest import base_config


def _fail_then(content, failures, status=500):
    """Responder: the first `failures` calls return `status`, then succeed."""

    def responder(payload, index):
        if index < failures:
            return Reply({"error": "server exploded"}, status=status)
        return Reply(completion(content))

    return responder


# Spec: "If a request receives an HTTP 5xx, retry it up to 3 times."
def test_transient_5xx_is_retried_and_then_succeeds(write_config, write_input, run_cli):
    with FakeAPIServer(_fail_then("#### 5", failures=2)) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)

    assert call_count == 3
    assert result.rows[0]["output"] == {"solution": "#### 5"}
    assert result.rows[0]["result"]["passed"] is True


# Spec: "Retry requests count toward total_api_calls, but for greedy and
# sample rows they do not increase the logical result.attempts count."
def test_retries_count_as_api_calls_but_not_attempts(write_config, write_input, run_cli):
    with FakeAPIServer(_fail_then("#### 5", failures=2)) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    assert result.rows[0]["result"]["attempts"] == 1
    assert result.summary["total_api_calls"] == 3


# Spec: "After the third failure, treat that row as failed, emit null output
# for it, count it as failed in the summary" (see AMBIGUITIES T2)
def test_persistent_5xx_fails_the_row(write_config, write_input, run_cli):
    with FakeAPIServer(_fail_then("#### 5", failures=99)) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)

    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert result.summary["failed"] == 1
    assert result.summary["passed"] == 0
    assert call_count == 4  # one initial request plus three retries


# Spec: "... and continue." - other rows still complete
def test_processing_continues_after_a_failed_row(write_config, write_input, run_cli):
    def responder(payload, index):
        if payload["messages"][1]["content"] == "bad":
            return Reply({"error": "boom"}, status=503)
        return Reply(completion("#### 5"))

    with FakeAPIServer(responder) as api:
        config = write_config(base_config(api.url))
        rows = write_input([
            {"question": "bad", "answer": "5"},
            {"question": "good", "answer": "5"},
            {"question": "good", "answer": "5"},
        ])
        result = run_cli(config, rows)

    assert result.returncode == 0
    assert result.rows[0]["output"] is None
    assert result.rows[1]["output"] == {"solution": "#### 5"}
    assert result.rows[2]["output"] == {"solution": "#### 5"}
    assert (result.summary["total"], result.summary["passed"], result.summary["failed"]) == (3, 2, 1)


# Spec: "emit null output for it" - the failed row still carries a result block
def test_failed_row_result_block(write_config, write_input, run_cli):
    with FakeAPIServer(_fail_then("#### 5", failures=99)) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    assert result.rows[0]["result"]["extracted_answer"] is None
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: retries apply to 5xx; other HTTP errors are not retried
# (see AMBIGUITIES T9)
def test_4xx_is_not_retried(write_config, write_input, run_cli):
    def responder(payload, index):
        return Reply({"error": "bad request"}, status=400)

    with FakeAPIServer(responder) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)

    assert call_count == 1
    assert result.rows[0]["output"] is None
    assert result.summary["failed"] == 1


# Spec: "Retry requests count toward total_api_calls" for rejection rows too
def test_retries_inside_rejection_do_not_inflate_attempts(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.7, "n": 3, "max_tokens": 64}

    calls = {"n": 0}

    def responder(payload, index):
        calls["n"] += 1
        if calls["n"] == 1:
            return Reply({"error": "boom"}, status=500)
        return Reply(completion("#### 5"))

    with FakeAPIServer(responder) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    assert result.rows[0]["result"]["attempts"] == 1
    assert result.rows[0]["result"]["passed"] is True
    assert result.summary["total_api_calls"] == 2


# Spec: a row that never received a successful response has no per-call
# metadata to report (see AMBIGUITIES T7)
def test_failed_row_meta_is_null(write_config, write_input, run_cli):
    with FakeAPIServer(_fail_then("#### 5", failures=99)) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
    assert result.rows[0]["meta"] is None

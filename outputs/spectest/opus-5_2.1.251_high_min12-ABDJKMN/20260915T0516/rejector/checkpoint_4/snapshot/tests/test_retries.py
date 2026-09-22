"""HTTP 5xx retry behaviour and permanently failed rows."""
import threading

import pytest

from conftest import make_config
from mock_api import MockAPI, always, chat_response, status


def per_row_sequence(mapping, default=("#### 0",)):
    counts = {}
    lock = threading.Lock()

    def responder(payload, i):
        user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        with lock:
            k = counts.get(user, 0)
            counts[user] = k + 1
        seq = mapping.get(user, default)
        item = seq[k] if k < len(seq) else seq[-1]
        if isinstance(item, int):
            return item, {"error": "boom"}
        return 200, chat_response(item)
    return responder


ROW = {"question": "q", "answer": "5"}


# Spec: "If a request receives an HTTP 5xx, retry it up to 3 times."
# Context: API Contract.
def test_transient_5xx_is_retried_and_then_succeeds(run_tool):
    with MockAPI(status(500, times=1)) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    row = run.rows[0]
    assert row["output"] is not None
    assert row["result"]["passed"] is False  # "#### 42" vs answer "5"


def test_two_transient_5xx_then_success(run_tool):
    with MockAPI(status(503, times=2, then=always("#### 5"))) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    assert run.rows[0]["result"]["passed"] is True


# T3: three HTTP calls in total before the row is abandoned.
def test_persistent_5xx_gives_up_after_three_calls(run_tool):
    with MockAPI(status(500)) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3


# Spec: "After the third failure, treat that row as failed, emit null output
#        for it, count it as failed in the summary, and continue."
def test_failed_row_emits_null_output_and_is_counted_failed(run_tool):
    with MockAPI(status(500)) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] is None
    assert row["result"]["extracted_answer"] is None
    assert run.summary["failed"] == 1
    assert run.summary["passed"] == 0


def test_run_continues_after_a_failed_row(run_tool):
    # Row "bad" always 500s; the other rows still succeed and the run exits 0.
    responder = per_row_sequence({"bad": [500], "good1": ["#### 5"],
                                 "good2": ["#### 5"]})
    rows = [{"question": "good1", "answer": "5"},
            {"question": "bad", "answer": "5"},
            {"question": "good2", "answer": "5"}]
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    out = run.rows
    assert len(out) == 3
    assert out[0]["output"] is not None
    assert out[1]["output"] is None
    assert out[2]["output"] is not None
    assert run.summary["total"] == 3
    assert run.summary["passed"] == 2
    assert run.summary["failed"] == 1


# Spec: "Retry requests count toward total_api_calls, but for greedy and
#        sample rows they do not increase the logical result.attempts count."
def test_retries_count_toward_total_api_calls(run_tool):
    with MockAPI(status(500, times=2, then=always("#### 5"))) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.summary["total_api_calls"] == 3


def test_retries_do_not_increase_attempts_for_greedy(run_tool):
    with MockAPI(status(500, times=2, then=always("#### 5"))) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 1


def test_retries_do_not_increase_attempts_for_sample(run_tool):
    with MockAPI(status(502, times=1, then=always("#### 5"))) as api:
        run = run_tool(make_config(api_url=api.url, scheme="sample",
                                   temperature=0.5), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 1


def test_failed_row_attempts_is_one_for_greedy(run_tool):
    with MockAPI(status(500)) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 1


# T17: a retry inside a rejection attempt does not consume one of the n
# logical attempts.
def test_retry_inside_rejection_attempt_does_not_consume_an_attempt(run_tool):
    # First call 500s, retry returns a failing answer, second logical attempt
    # passes: attempts == 2, api calls == 3.
    responder = per_row_sequence({"q": [500, "#### 0", "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, scheme="rejection",
                                   temperature=0.7, n=3),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 3
    assert run.rows[0]["result"]["attempts"] == 2
    assert run.rows[0]["result"]["passed"] is True


# T4: when a rejection attempt exhausts its retries the whole row fails.
def test_rejection_row_fails_when_an_attempt_exhausts_retries(run_tool):
    responder = per_row_sequence({"q": ["#### 0", 500, 500, 500, "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, scheme="rejection",
                                   temperature=0.7, n=5),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["attempts"] == 2
    assert api.call_count == 4  # 1 good attempt + 3 calls for the dead attempt


# T2: meta for a row with no successful response at all.
def test_meta_is_null_when_no_call_succeeded(run_tool):
    with MockAPI(status(500)) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["meta"] is None


# T5: an API-failed row reports passed false even with an evaluation absent.
def test_failed_row_passed_is_false_without_evaluation(run_tool):
    with MockAPI(status(500)) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is False
    assert run.summary["failed"] == 1


# T14: a 4xx is not retried.
def test_4xx_is_not_retried_and_fails_the_row(run_tool):
    with MockAPI(status(400)) as api:
        run = run_tool(make_config(api_url=api.url), [ROW])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 1
    assert run.rows[0]["output"] is None
    assert run.summary["failed"] == 1


# T14: an unreachable server must not crash the run.
def test_connection_failure_fails_rows_without_crashing(run_tool):
    run = run_tool(make_config(api_url="http://127.0.0.1:1"), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] is None
    assert run.summary["failed"] == 1
    assert run.summary["total_api_calls"] == 3

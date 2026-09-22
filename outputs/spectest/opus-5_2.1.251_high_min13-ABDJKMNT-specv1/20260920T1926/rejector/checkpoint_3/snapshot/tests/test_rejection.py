"""Rejection sampling: attempt loop, kept response, metadata list."""

from __future__ import annotations

from conftest import base_task
from fake_api import FakeAPI, Reply, always, sequence


def rejection_task(api_url: str, n: int = 3, temperature: float = 0.8) -> dict:
    task = base_task(api_url)
    task["generation"] = {"scheme": "rejection", "temperature": temperature, "n": n}
    return task


# Spec: "rejection: ... make up to n attempts and keep the first passing
# response"
# Context: Generation behavior; a first-attempt pass stops there.
def test_first_attempt_pass_stops_immediately(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(rejection_task(api.url, n=5))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 1
    row = result.rows[0]
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}


# Spec: "meta is a single metadata object for one-attempt rows"
# Context: Output rules (see AMBIGUITIES T13).
def test_single_attempt_rejection_meta_is_an_object(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        config = write_config(rejection_task(api.url, n=3))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
    assert isinstance(result.rows[0]["meta"], dict)


# Spec: "Rejection example with n: 3: if the first two responses fail
# evaluation and the third passes, the output row records attempts: 3, keeps
# the third response as output, and includes three metadata entries."
# Context: Examples.
def test_third_attempt_passes(write_config, write_input, run_cli):
    script = [Reply(content="#### 1"), Reply(content="#### 2"), Reply(content="#### 5")]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(rejection_task(api.url, n=3))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 3
    row = result.rows[0]
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 3}
    assert row["output"] == {"solution": "#### 5"}
    assert isinstance(row["meta"], list)
    assert len(row["meta"]) == 3


# Spec: "if all attempts fail, output null with "passed": false"
# Context: Generation behavior, matching the exhausted-rejection example.
def test_all_attempts_fail(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1")) as api:
        config = write_config(rejection_task(api.url, n=5))
        data = write_input([{"question": "q", "answer": "42"}])
        result = run_cli(config, data)
        assert api.call_count == 5
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 5}
    assert len(row["meta"]) == 5


# Spec: "result.attempts is the number of logical generation attempts for that
# row: ... 1..n for rejection"
# Context: Output rules.
def test_attempts_never_exceeds_n(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1")) as api:
        config = write_config(rejection_task(api.url, n=2))
        data = write_input([{"question": "q", "answer": "42"}])
        result = run_cli(config, data)
        assert api.call_count == 2
    assert result.rows[0]["result"]["attempts"] == 2


# Spec: "rejection: temperature must be > 0"
# Context: Generation behavior; every attempt uses that temperature.
def test_every_attempt_uses_the_configured_temperature(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 1")) as api:
        config = write_config(rejection_task(api.url, n=3, temperature=0.9))
        data = write_input([{"question": "q", "answer": "42"}])
        run_cli(config, data)
        assert [body["temperature"] for body in api.requests] == [0.9, 0.9, 0.9]


# Spec: "total_api_calls: all HTTP requests, including retries and rejection
# attempts"
# Context: Summary rules.
def test_rejection_attempts_and_retries_both_counted(write_config, write_input, run_cli):
    script = [
        Reply(content="#### 1"),   # attempt 1: fails evaluation
        Reply(status=500),         # attempt 2: retried
        Reply(content="#### 5"),   # attempt 2 retry: passes
    ]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(rejection_task(api.url, n=3))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 3
    row = result.rows[0]
    assert row["result"]["attempts"] == 2
    assert len(row["meta"]) == 2
    assert result.summary["total_api_calls"] == 3


# Spec: "After the third failure, treat that row as failed, emit null output
# for it" — applies inside rejection too.
# Context: API Contract.
def test_exhausted_retries_fail_the_rejection_row(write_config, write_input, run_cli):
    script = [Reply(content="#### 1")] + [Reply(status=500)] * 3
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(rejection_task(api.url, n=5))
        data = write_input([{"question": "q", "answer": "5"}])
        result = run_cli(config, data)
        assert api.call_count == 4
    row = result.rows[0]
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["attempts"] == 2
    assert result.summary["failed"] == 1


# Spec: "rejection ... keep the first passing response"
# Context: Generation behavior; later rows still run concurrently and keep
# their own attempts.
def test_multiple_rejection_rows_keep_their_own_attempts(write_config, write_input, run_cli):
    def responder(index, body):
        question = body["messages"][-1]["content"]
        # "easy" passes at once; "hard" needs its answer on the third attempt.
        if question == "easy":
            return Reply(content="#### 5")
        return Reply(content="#### 5" if _hard_calls(body, index) else "#### 0")

    seen: dict[str, int] = {}

    def _hard_calls(body, index):
        question = body["messages"][-1]["content"]
        seen[question] = seen.get(question, 0) + 1
        return seen[question] >= 3

    with FakeAPI(responder=responder, slots=4, delay=0.02) as api:
        config = write_config(rejection_task(api.url, n=4))
        data = write_input(
            [{"question": "hard", "answer": "5"}, {"question": "easy", "answer": "5"}]
        )
        result = run_cli(config, data)
    rows = result.rows
    assert rows[0]["input"]["question"] == "hard"
    assert rows[0]["result"]["attempts"] == 3
    assert rows[1]["result"]["attempts"] == 1

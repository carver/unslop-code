"""Generation schemes: greedy, sample, rejection."""

from __future__ import annotations

from tests.conftest import task_config
from tests.fake_api import error, ok

ROW = {"question": "What is 2 + 3?", "answer": "5"}


def rejection_config(server, n=3, **overrides):
    return task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "n": n},
        **overrides,
    )


# "greedy: force temperature to 0.0; n is ignored"
def test_greedy_ignores_n(cli, static_api):
    server = static_api("#### 9")  # fails evaluation, yet greedy must not retry
    config = task_config(api_url=server.url, generation={"scheme": "greedy", "n": 5})
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    assert len(server.log.calls) == 1
    assert run.rows[0]["result"]["attempts"] == 1
    assert run.rows[0]["result"]["passed"] is False


# "sample: temperature must be > 0; n is ignored"
def test_sample_ignores_n(cli, static_api):
    server = static_api("#### 9")
    config = task_config(
        api_url=server.url,
        generation={"scheme": "sample", "temperature": 0.7, "n": 5},
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    assert len(server.log.calls) == 1
    assert run.rows[0]["result"]["attempts"] == 1


# "rejection: make up to n attempts and keep the first passing response"
# "Rejection example with n: 3: if the first two responses fail evaluation and
#  the third passes, the output row records attempts: 3, keeps the third
#  response as output, and includes three metadata entries."
def test_rejection_keeps_first_passing_response(cli, api):
    def responder(index, body):
        return ok("#### 4") if index < 2 else ok("#### 5")

    server = api(responder)
    run = cli.run(rejection_config(server, n=3), [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 3}
    assert row["output"] == {"solution": "#### 5"}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 3
    assert len(server.log.calls) == 3


# "make up to n attempts and keep the first passing response" - a pass on the
# first attempt stops there
def test_rejection_stops_at_first_pass(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(rejection_config(server, n=4), [ROW])
    assert run.returncode == 0
    assert len(server.log.calls) == 1
    assert run.rows[0]["result"]["attempts"] == 1
    # T14: one attempt means one metadata object, not a list
    assert isinstance(run.rows[0]["meta"], dict)


# "if all attempts fail, output null with "passed": false"
# '{"output": null, "result": {"passed": false, "extracted_answer": null,
#   "attempts": 5}, "meta": [{...} x5]}'
def test_rejection_exhausted_emits_null_output(cli, static_api):
    server = static_api("#### 9")
    run = cli.run(rejection_config(server, n=5), [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 5}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 5
    assert len(server.log.calls) == 5


# "result.attempts is ... 1..n for rejection"
def test_rejection_attempts_never_exceed_n(cli, static_api):
    server = static_api("#### 9")
    run = cli.run(rejection_config(server, n=2), [ROW])
    assert run.returncode == 0
    assert run.rows[0]["result"]["attempts"] == 2


# T8: an attempt whose retries are exhausted counts as a failed attempt and the
# remaining attempts still run
def test_rejection_continues_after_api_failure(cli, api):
    def responder(index, body):
        return error(500) if index < 3 else ok("#### 5")

    server = api(responder)
    run = cli.run(rejection_config(server, n=3), [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert row["result"]["passed"] is True
    assert row["result"]["attempts"] == 2  # first attempt burned 3 HTTP calls
    assert run.summary["total_api_calls"] == 4
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2


# "rejection: temperature must be > 0" - every attempt samples at that
# temperature
def test_rejection_sends_configured_temperature_each_attempt(cli, static_api):
    server = static_api("#### 9")
    run = cli.run(rejection_config(server, n=3), [ROW])
    assert run.returncode == 0
    assert [body["temperature"] for body in server.log.bodies] == [0.8, 0.8, 0.8]


# "rejection" with a contains evaluation still keeps the first passing response
def test_rejection_with_contains_evaluation(cli, api):
    def responder(index, body):
        return ok("nope") if index == 0 else ok("the answer is 5 indeed")

    server = api(responder)
    config = rejection_config(server, n=3, evaluation={
        "type": "contains", "answer_field": "answer",
    })
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    assert run.rows[0]["result"]["attempts"] == 2
    assert run.rows[0]["output"] == {"solution": "the answer is 5 indeed"}


# "if evaluation is omitted for greedy or sample, result.passed must be null"
def test_no_evaluation_yields_null_passed(cli, static_api):
    server = static_api("anything at all")
    config = task_config(api_url=server.url)
    config["task"].pop("evaluation")
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert row["result"]["passed"] is None
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["attempts"] == 1
    assert row["output"] == {"solution": "anything at all"}


# "regex: response text must match the configured pattern" end to end
def test_regex_evaluation_end_to_end(cli, static_api):
    server = static_api("work\n#### 17")
    config = task_config(api_url=server.url, evaluation={
        "type": "regex", "pattern": r"####\s*\d+", "answer_field": None,
    })
    run = cli.run(config, [{"question": "q"}])
    assert run.returncode == 0
    assert run.rows[0]["result"]["passed"] is True

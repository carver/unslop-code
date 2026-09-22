"""Rejection sampling: up to n attempts, first passing response wins."""

from __future__ import annotations

from fake_server import FakeAPIServer, always, cycle
from conftest import base_config


def _rejection_config(api_url, n=3, **evaluation):
    config_map = base_config(api_url)
    config_map["task"]["generation"] = {
        "scheme": "rejection", "temperature": 0.8, "max_tokens": 64, "n": n,
    }
    if evaluation:
        config_map["task"]["evaluation"] = evaluation
    return config_map


# Spec: "rejection: ... make up to n attempts and keep the first passing
# response" - the spec's worked example with n: 3
def test_third_attempt_passes_and_is_kept(write_config, write_input, run_cli):
    with FakeAPIServer(cycle(["#### 1", "#### 2", "#### 5"])) as api:
        config = write_config(_rejection_config(api.url, n=3))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)

    row = result.rows[0]
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"solution": "#### 5"}
    assert row["result"]["passed"] is True
    assert len(row["meta"]) == 3
    assert call_count == 3


# Spec: "keep the first passing response" - later attempts are not made
def test_passing_first_attempt_stops_further_attempts(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(_rejection_config(api.url, n=5))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)

    assert call_count == 1
    assert result.rows[0]["result"]["attempts"] == 1
    assert result.rows[0]["result"]["passed"] is True


# Spec: "result.attempts is ... 1..n for rejection"
def test_attempts_counts_the_passing_attempt(write_config, write_input, run_cli):
    with FakeAPIServer(cycle(["#### 1", "#### 5"])) as api:
        config = write_config(_rejection_config(api.url, n=4))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
        call_count = len(api.requests)
    assert result.rows[0]["result"]["attempts"] == 2
    assert call_count == 2


# Spec: "if all attempts fail, output null with "passed": false"
def test_exhausted_attempts_emit_null_output(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 9")) as api:
        config = write_config(_rejection_config(api.url, n=5))
        result = run_cli(config, write_input([{"question": "q", "answer": "42"}]))
        call_count = len(api.requests)

    row = result.rows[0]
    assert row["output"] is None
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 5}
    assert len(row["meta"]) == 5
    assert call_count == 5


# Spec: "result.extracted_answer is ... null when there is ... no output"
def test_extracted_answer_is_null_when_output_is_null(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 9")) as api:
        config = write_config(_rejection_config(api.url, n=2))
        result = run_cli(config, write_input([{"question": "q", "answer": "42"}]))
    assert result.rows[0]["result"]["extracted_answer"] is None


# Spec: rejection uses the configured temperature, which must be > 0
def test_rejection_sends_the_configured_temperature(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 9")) as api:
        config = write_config(_rejection_config(api.url, n=2))
        run_cli(config, write_input([{"question": "q", "answer": "42"}]))
        temperatures = [p["temperature"] for p in api.payloads]
    assert temperatures == [0.8, 0.8]


# Spec: "make up to n attempts" - with n omitted the default is a single attempt
def test_rejection_defaults_to_one_attempt(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.8, "max_tokens": 64}
    with FakeAPIServer(always("#### 9")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q", "answer": "42"}]))
        call_count = len(api.requests)
    assert call_count == 1
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "meta is a single metadata object for one-attempt rows" - this holds
# for rejection rows that pass on the first attempt (see AMBIGUITIES T6)
def test_single_attempt_rejection_row_has_object_meta(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(_rejection_config(api.url, n=3))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
    assert isinstance(result.rows[0]["meta"], dict)


# Spec: rejection evaluates each attempt independently across rows
def test_rejection_handles_multiple_rows_independently(write_config, write_input, run_cli):
    def responder(payload, index):
        from fake_server import Reply, completion
        question = payload["messages"][1]["content"]
        # "easy" passes immediately; "hard" never passes.
        return Reply(completion("#### 5" if question == "easy" else "#### 0"))

    with FakeAPIServer(responder) as api:
        config = write_config(_rejection_config(api.url, n=3))
        rows = write_input([{"question": "easy", "answer": "5"}, {"question": "hard", "answer": "5"}])
        result = run_cli(config, rows)
        call_count = len(api.requests)

    assert result.rows[0]["result"]["attempts"] == 1
    assert result.rows[0]["result"]["passed"] is True
    assert result.rows[1]["result"]["attempts"] == 3
    assert result.rows[1]["output"] is None
    assert call_count == 4

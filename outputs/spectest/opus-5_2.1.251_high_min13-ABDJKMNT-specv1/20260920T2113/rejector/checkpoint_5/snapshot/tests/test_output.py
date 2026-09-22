"""Per-row output shape and ordering rules."""

from __future__ import annotations

from tests.conftest import task_config
from tests.fake_api import error, ok

ROW = {"question": "What is 2 + 3?", "answer": "5"}
META_KEYS = {
    "model", "prompt_tokens", "completion_tokens", "total_tokens",
    "latency_ms", "finish_reason",
}


# "Write one JSON object per input row, in the same order as the input."
# "Output row: {"input": ..., "output": ..., "result": ..., "meta": ...}"
def test_row_shape_matches_the_greedy_example(cli, api):
    server = api(lambda index, body: ok(
        "2 + 3 = 5\n#### 5", prompt_tokens=30, completion_tokens=10,
    ))
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert set(row) == {"input", "output", "result", "meta"}
    assert row["input"] == ROW
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert set(row["meta"]) == META_KEYS
    assert row["meta"]["model"] == "gpt-4"
    assert row["meta"]["prompt_tokens"] == 30
    assert row["meta"]["completion_tokens"] == 10
    assert row["meta"]["total_tokens"] == 40
    assert row["meta"]["finish_reason"] == "stop"
    assert isinstance(row["meta"]["latency_ms"], int)


# "input is the original row, unchanged"
def test_input_row_is_unchanged(cli, static_api):
    server = static_api("#### 5")
    original = {"question": "What is 2 + 3?", "answer": "5", "extra": {"nested": [1, 2]}, "id": 7}
    run = cli.run(task_config(api_url=server.url), [original])
    assert run.returncode == 0
    assert run.rows[0]["input"] == original


# "output is an object with one key named by output_field"
def test_output_key_comes_from_output_field(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url, output_field="completion"), [ROW])
    assert run.returncode == 0
    assert run.rows[0]["output"] == {"completion": "#### 5"}


# "if all attempts fail, output is null"
def test_output_is_null_when_all_attempts_fail(cli, api):
    server = api(lambda index, body: error(500))
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    row = run.rows[0]
    assert row["output"] is None
    # "result.extracted_answer is ... null when there is no evaluation or no output"
    assert row["result"] == {"passed": False, "extracted_answer": None, "attempts": 1}
    # T3: meta keeps its documented shape for a row with no successful response
    assert set(row["meta"]) == META_KEYS
    assert row["meta"]["finish_reason"] is None


# "result.passed is true for a passing evaluation, false for a failing
#  evaluation, and null when no evaluation is configured"
def test_passed_tracks_the_evaluation(cli, static_api):
    server = static_api("#### 4")
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert run.rows[0]["result"]["passed"] is False
    # a failing evaluation still keeps the generated output
    assert run.rows[0]["output"] == {"solution": "#### 4"}
    assert run.rows[0]["result"]["extracted_answer"] == "4"


# "result.attempts is ... 1 for greedy and sample"
def test_attempts_is_one_for_greedy(cli, static_api):
    server = static_api("#### 5")
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert run.rows[0]["result"]["attempts"] == 1


# "meta is a single metadata object for one-attempt rows; for rejection sampling
#  with multiple attempts it is a list with one metadata object per attempt"
def test_meta_is_a_list_only_for_multi_attempt_rows(cli, api):
    def responder(index, body):
        return ok("#### 4") if index == 0 else ok("#### 5")

    server = api(responder)
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.8, "n": 3},
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0
    meta = run.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 2
    assert all(set(entry) == META_KEYS for entry in meta)


# "meta.latency_ms is wall-clock latency for that API call"
def test_latency_reflects_server_delay(cli, api):
    server = api(lambda index, body: ok("#### 5"), delay=0.25)
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0
    assert run.rows[0]["meta"]["latency_ms"] >= 250


# "Write one JSON object per input row, in the same order as the input."
# "Send requests in input order: concurrent execution must not cause a later
#  input row to consume the response intended for an earlier row."
def test_rows_keep_input_order_under_concurrency(cli, api):
    # Each response echoes the question it was asked, so a mismatch is visible.
    def responder(index, body):
        question = body["messages"][-1]["content"]
        return ok(f"solving {question}\n#### {question}")

    server = api(responder, delay=0.05)
    rows = [{"question": str(value), "answer": str(value)} for value in range(30)]
    run = cli.run(task_config(api_url=server.url, rpm=600), rows)
    assert run.returncode == 0
    assert [row["input"] for row in run.rows] == rows
    for row in run.rows:
        assert row["output"]["solution"].endswith(f"#### {row['input']['question']}")
        assert row["result"]["passed"] is True

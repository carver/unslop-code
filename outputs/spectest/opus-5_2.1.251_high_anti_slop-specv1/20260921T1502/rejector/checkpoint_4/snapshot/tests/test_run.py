"""End to end runs of the CLI against the mock API server."""

import json

import pytest
import yaml
from mock_server import start_mock_server

import rejector

TASK = {
    "name": "math_solve",
    "model": "gpt-4",
    "rpm": 600,
    "prompt": {"system": "Solve the math problem.", "user": "{question}"},
    "generation": {"scheme": "greedy", "max_tokens": 256},
    "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
    "output_field": "solution",
}


@pytest.fixture
def api():
    """Start a mock server whose responder the test installs afterwards."""
    servers = []

    def start(responder, delay=0.0, capacity=8):
        url, state, shutdown = start_mock_server(responder, delay=delay, capacity=capacity)
        servers.append(shutdown)
        return url, state

    yield start
    for shutdown in servers:
        shutdown()


def run(tmp_path, url, rows, capsys, **task):
    """Run the CLI over `rows` and return `(exit_code, records, summary)`."""
    config = {**TASK, **task, "api_url": url}
    (tmp_path / "task.yaml").write_text(yaml.safe_dump({"task": config}))
    (tmp_path / "in.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    code = rejector.main(
        [
            "run",
            "--config", str(tmp_path / "task.yaml"),
            "--input", str(tmp_path / "in.jsonl"),
            "--output", str(tmp_path / "out.jsonl"),
        ]
    )
    stdout = capsys.readouterr().out
    output = tmp_path / "out.jsonl"
    records = [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []
    return code, records, json.loads(stdout) if stdout.strip() else None


def test_greedy_row_matches_the_documented_shape(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "2 + 3 = 5\n#### 5")
    code, records, summary = run(tmp_path, url, [{"question": "What is 2 + 3?", "answer": "5"}], capsys)

    assert code == 0
    assert records[0]["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert records[0]["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert records[0]["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert records[0]["meta"]["model"] == "gpt-4"
    assert records[0]["meta"]["finish_reason"] == "stop"
    assert records[0]["meta"]["latency_ms"] >= 0
    assert summary["total"] == summary["passed"] == summary["total_api_calls"] == 1
    assert summary["total_prompt_tokens"] == 10 and summary["total_completion_tokens"] == 5
    assert state.calls[0]["temperature"] == 0.0
    assert state.calls[0]["messages"][0] == {"role": "system", "content": "Solve the math problem."}


def test_failing_evaluation_keeps_the_response(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 7")
    _, records, summary = run(tmp_path, url, [{"question": "What is 2 + 3?", "answer": "5"}], capsys)

    assert records[0]["output"] == {"solution": "#### 7"}
    assert records[0]["result"] == {"passed": False, "extracted_answer": "7", "attempts": 1}
    assert (summary["passed"], summary["failed"]) == (0, 1)


def test_sample_scheme_sends_the_configured_temperature(tmp_path, api, capsys):
    url, state = api(lambda payload, call: "#### 5")
    run(
        tmp_path, url, [{"question": "q", "answer": "5"}], capsys,
        generation={"scheme": "sample", "temperature": 0.8, "max_tokens": 64},
    )
    assert state.calls[0]["temperature"] == 0.8
    assert state.calls[0]["max_tokens"] == 64


def test_without_evaluation_the_verdict_is_null(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "hello")
    _, records, summary = run(tmp_path, url, [{"question": "q"}], capsys, evaluation=None)

    assert records[0]["result"] == {"passed": None, "extracted_answer": None, "attempts": 1}
    assert summary["passed"] == 1


def test_rejection_keeps_the_first_passing_attempt(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 5" if call == 3 else "#### 0")
    _, records, summary = run(
        tmp_path, url, [{"question": "q", "answer": "5"}], capsys,
        generation={"scheme": "rejection", "temperature": 0.9, "n": 5, "max_tokens": 64},
    )

    assert records[0]["output"] == {"solution": "#### 5"}
    assert records[0]["result"] == {"passed": True, "extracted_answer": "5", "attempts": 3}
    assert len(records[0]["meta"]) == 3
    assert summary["total_api_calls"] == 3


def test_rejection_exhausted_emits_a_null_output(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 0")
    _, records, summary = run(
        tmp_path, url, [{"question": "q", "answer": "5"}], capsys,
        generation={"scheme": "rejection", "temperature": 0.9, "n": 4, "max_tokens": 64},
    )

    assert records[0]["output"] is None
    assert records[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 4}
    assert len(records[0]["meta"]) == 4
    assert (summary["failed"], summary["total_api_calls"]) == (1, 4)


def test_server_errors_are_retried_three_times_then_fail_the_row(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: 503)
    _, records, summary = run(tmp_path, url, [{"question": "q", "answer": "5"}], capsys)

    assert records[0]["output"] is None and records[0]["meta"] is None
    assert records[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 1}
    assert (summary["failed"], summary["total_api_calls"]) == (1, 3)


def test_a_retried_row_still_succeeds(tmp_path, api, capsys):
    url, _ = api(lambda payload, call: "#### 5" if call == 2 else 500)
    _, records, summary = run(tmp_path, url, [{"question": "q", "answer": "5"}], capsys)

    assert records[0]["result"]["attempts"] == 1
    assert (summary["passed"], summary["total_api_calls"]) == (1, 2)


def test_responses_stay_paired_with_their_own_row(tmp_path, api, capsys):
    rows = [{"question": f"question {index}", "answer": str(index)} for index in range(24)]
    url, _ = api(lambda payload, call: f"#### {payload['messages'][-1]['content'].split()[-1]}", delay=0.05)
    _, records, summary = run(tmp_path, url, rows, capsys)

    assert [record["input"] for record in records] == rows
    assert all(record["result"]["passed"] for record in records)
    assert summary["passed"] == 24


def test_throughput_uses_the_configured_request_budget(tmp_path, api, capsys):
    rows = [{"question": f"question {index}", "answer": "5"} for index in range(40)]
    # 600 rpm of capacity means 10 requests per second: five concurrent 0.5s requests.
    # A sequential client would need 20 seconds for these rows; the budget allows 4.
    url, _ = api(lambda payload, call: "#### 5", delay=0.5, capacity=5)
    _, _, summary = run(tmp_path, url, rows, capsys, rpm=600)

    assert summary["throughput_rpm"] >= 0.8 * 600

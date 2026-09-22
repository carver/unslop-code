"""End-to-end tests driving rejector.py against the mock API server."""

EXACT_MATCH = """  evaluation:
    type: "exact_match"
    answer_field: "answer"
    extract: "last_number"
"""
NO_EVALUATION = ""


def task_config(url, *, scheme="greedy", temperature=0.0, n=1, evaluation=EXACT_MATCH, rpm=600):
    """Build a task config pointed at the mock server."""
    return f"""
task:
  name: "mock_task"
  api_url: "{url}"
  model: "mock-model"
  rpm: {rpm}
  prompt:
    system: "Solve the problem. Final answer after ####."
    user: "{{question}}"
  generation:
    scheme: "{scheme}"
    temperature: {temperature}
    max_tokens: 64
    n: {n}
{evaluation}  output_field: "solution"
"""


def test_greedy_records_pass_and_fail(mock_server, run_cli):
    server = mock_server()
    rows = [{"question": "two plus six?", "answer": "8"}, {"question": "two plus seven?", "answer": "9"}]

    completed, summary, results = run_cli(task_config(server.url), rows)

    assert completed.returncode == 0, completed.stderr
    assert [result["result"]["passed"] for result in results] == [True, False]
    assert [result["result"]["extracted_answer"] for result in results] == ["8", "8"]
    assert [result["result"]["attempts"] for result in results] == [1, 1]
    assert results[0]["input"] == rows[0]
    assert results[0]["output"]["solution"].endswith("#### 8")
    assert results[0]["meta"]["model"] == "mock-model"
    assert results[0]["meta"]["finish_reason"] == "stop"
    assert results[0]["meta"]["latency_ms"] >= 0
    assert summary["total"] == 2 and summary["passed"] == 1 and summary["failed"] == 1
    assert summary["total_api_calls"] == 2
    assert summary["total_prompt_tokens"] > 0 and summary["total_completion_tokens"] > 0
    assert "tasks" not in summary


def test_greedy_forces_zero_temperature(mock_server, run_cli):
    server = mock_server()
    rows = [{"question": "two plus six?", "answer": "8"}]

    _, _, results = run_cli(task_config(server.url, temperature=0.9), rows)

    assert "temp=0.0" in results[0]["output"]["solution"]


def test_sample_scheme_sends_configured_temperature(mock_server, run_cli):
    server = mock_server()
    rows = [{"question": "two plus six?", "answer": "8"}]

    _, _, results = run_cli(task_config(server.url), rows, "--scheme", "sample", "--temperature", "0.7")

    assert "temp=0.7" in results[0]["output"]["solution"]


def test_missing_evaluation_leaves_passed_null(mock_server, run_cli):
    server = mock_server()
    rows = [{"question": "two plus six?"}]

    _, summary, results = run_cli(task_config(server.url, evaluation=NO_EVALUATION), rows)

    assert results[0]["result"] == {"passed": None, "extracted_answer": None, "attempts": 1}
    assert summary["passed"] == 1


def test_rejection_keeps_first_passing_attempt(mock_server, run_cli):
    server = mock_server("--pass-after", "2")
    rows = [{"question": "two plus six?", "answer": "8"}]

    _, summary, results = run_cli(task_config(server.url, scheme="rejection", temperature=0.8, n=3), rows)

    assert results[0]["result"] == {"passed": True, "extracted_answer": "8", "attempts": 3}
    assert results[0]["output"]["solution"].endswith("#### 8")
    assert len(results[0]["meta"]) == 3
    assert summary["total_api_calls"] == 3 and summary["passed"] == 1


def test_rejection_exhausts_attempts(mock_server, run_cli):
    server = mock_server("--pass-after", "10")
    rows = [{"question": "two plus six?", "answer": "8"}]

    _, summary, results = run_cli(task_config(server.url, scheme="rejection", temperature=0.8, n=4), rows)

    assert results[0]["output"] is None
    assert results[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 4}
    assert len(results[0]["meta"]) == 4
    assert summary["passed"] == 0 and summary["failed"] == 1 and summary["total_api_calls"] == 4


def test_server_errors_are_retried_three_times(mock_server, run_cli):
    server = mock_server("--always-fail")
    rows = [{"question": "two plus six?", "answer": "8"}]

    _, summary, results = run_cli(task_config(server.url), rows)

    assert results[0]["output"] is None
    assert results[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 1}
    assert results[0]["meta"]["error"] == "server returned HTTP 503"
    assert summary["total_api_calls"] == 3 and summary["failed"] == 1


def test_missing_prompt_field_is_an_input_error(mock_server, run_cli):
    server = mock_server()

    completed, _, results = run_cli(task_config(server.url), [{"text": "hello", "answer": "8"}])

    assert completed.returncode == 1
    assert "row 0" in completed.stderr and "question" in completed.stderr
    assert results == []


def test_missing_answer_field_is_an_input_error(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(task_config(server.url), [{"question": "two plus six?"}])

    assert completed.returncode == 1
    assert "row 0" in completed.stderr and "answer" in completed.stderr


def test_sample_requires_positive_temperature(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(task_config(server.url, scheme="sample", temperature=0.0), [{"question": "x", "answer": "8"}])

    assert completed.returncode == 1
    assert "temperature" in completed.stderr


def test_rejection_requires_an_evaluation(mock_server, run_cli):
    server = mock_server()
    config = task_config(server.url, scheme="rejection", temperature=0.5, evaluation=NO_EVALUATION)

    completed, _, _ = run_cli(config, [{"question": "x"}])

    assert completed.returncode == 1
    assert "evaluation" in completed.stderr


def test_unknown_scheme_is_a_config_error(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(task_config(server.url), [{"question": "x", "answer": "8"}], "--scheme", "beam")

    assert completed.returncode == 1
    assert "scheme" in completed.stderr


def test_concurrency_uses_the_request_budget_and_preserves_order(mock_server, run_cli):
    server = mock_server("--latency", "0.25", "--capacity", "25")
    rows = [{"question": f"row {index}?", "answer": "8"} for index in range(100)]

    completed, summary, results = run_cli(task_config(server.url, rpm=600), rows)

    assert completed.returncode == 0, completed.stderr
    assert summary["throughput_rpm"] >= 0.8 * 600
    assert summary["elapsed_seconds"] < len(rows) * 0.25
    for index, result in enumerate(results):
        assert result["input"] == rows[index]
        assert f"row {index}?" in result["output"]["solution"]

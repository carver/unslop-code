"""End-to-end tests for multi-task configs, llm_judge, and script evaluation."""

import json

import pytest

MULTI_CONFIG = """
defaults:
  api_url: "{url}"
  model: "mock-model"
  rpm: 600
  generation:
    max_tokens: 64

tasks:
  mmlu:
    prompt:
      system: "Answer the multiple choice question with a single letter."
      user: "{{question}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "letter"
    output_field: "choice"

  review:
    prompt:
      system: "You are a writing assistant."
      user: "{{prompt_text}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "llm_judge"
      judge_prompt:
        system: "You are a judge. Reply with a single integer from 1 to 10."
        user: "Rate this response:\\n{{__response__}}\\n\\nCriteria: {{criteria}}\\n\\nScore:"
      threshold: 7
      extract: "first_number"
    output_field: "response"

  code_gen:
    prompt:
      system: "Write the code."
      user: "{{problem}}"
    generation:
      scheme: "greedy"
    evaluation:
      type: "script"
      command_template: "{{test_code}}"
      success_exit_code: 0
    output_field: "code"
"""

MMLU_ROWS = [
    {"question": "capital of France?", "answer": "B"},
    {"question": "closest planet to the Sun?", "answer": "C"},
]
REVIEW_ROWS = [{"prompt_text": "describe a sunrise", "criteria": "vividness"}]
CODE_ROWS = [
    {"problem": "echo the prompt", "test_code": "echo '{__response__}' | grep -q 'echo:'"},
    {"problem": "echo the prompt", "test_code": "echo '{__response__}' | grep -q 'absent marker'"},
]


@pytest.fixture
def workspace(tmp_path):
    """Write the multi-task config and one input file per task into ``tmp_path``."""

    def setup(url):
        config = tmp_path / "multi.yaml"
        config.write_text(MULTI_CONFIG.format(url=url), encoding="utf-8")
        data = tmp_path / "data"
        data.mkdir()
        for name, rows in (("mmlu", MMLU_ROWS), ("review", REVIEW_ROWS), ("code_gen", CODE_ROWS)):
            path = data / f"{name}.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return config, data, tmp_path / "results"

    return setup


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_directory_mode_runs_every_task(mock_server, workspace, run_rejector):
    server = mock_server("--answer", "B", "--judge-score", "8")
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config), "--input-dir", str(data), "--output", str(results)
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert set(summary["tasks"]) == {"mmlu", "review", "code_gen"}
    assert summary["tasks"]["mmlu"] == {"total": 2, "passed": 1, "failed": 1, "total_api_calls": 2}
    assert summary["tasks"]["review"] == {"total": 1, "passed": 1, "failed": 0, "total_api_calls": 2}
    assert summary["tasks"]["code_gen"] == {"total": 2, "passed": 1, "failed": 1, "total_api_calls": 2}
    assert summary["total"] == 5 and summary["total_api_calls"] == 6

    mmlu = read(results / "mmlu.jsonl")
    assert [row["result"]["extracted_answer"] for row in mmlu] == ["B", "B"]
    assert [row["result"]["passed"] for row in mmlu] == [True, False]
    assert [row["input"] for row in mmlu] == MMLU_ROWS
    assert mmlu[0]["output"]["choice"].endswith("#### B")


def test_llm_judge_scores_and_reports_its_call(mock_server, workspace, run_rejector):
    server = mock_server("--judge-score", "8")
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config), "--input-dir", str(data), "--output", str(results), "--task", "review"
    )

    assert completed.returncode == 0, completed.stderr
    review = read(results / "review.jsonl")[0]
    assert review["result"]["judge_score"] == 8
    assert review["result"]["extracted_answer"] == "8"
    assert review["result"]["passed"] is True
    assert review["meta"]["judge_meta"]["model"] == "mock-model"
    assert review["meta"]["judge_meta"]["finish_reason"] == "stop"
    assert review["meta"]["judge_meta"]["latency_ms"] >= 0
    assert json.loads(completed.stdout)["tasks"] == {
        "review": {"total": 1, "passed": 1, "failed": 0, "total_api_calls": 2}
    }


def test_llm_judge_below_threshold_fails(mock_server, workspace, run_rejector):
    server = mock_server("--judge-score", "3")
    config, data, results = workspace(server.url)

    run_rejector(
        "--config", str(config), "--input-dir", str(data), "--output", str(results), "--task", "review"
    )

    review = read(results / "review.jsonl")[0]
    assert review["result"]["judge_score"] == 3
    assert review["result"]["passed"] is False


def test_eval_model_overrides_the_judge_model(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    run_rejector(
        "--config", str(config),
        "--input-dir", str(data),
        "--output", str(results),
        "--task", "review",
        "--eval-model", "judge-model",
    )

    review = read(results / "review.jsonl")[0]
    assert review["meta"]["model"] == "mock-model"
    assert review["meta"]["judge_meta"]["model"] == "judge-model"


def test_script_evaluation_uses_the_exit_code(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    run_rejector(
        "--config", str(config), "--input-dir", str(data), "--output", str(results), "--task", "code_gen"
    )

    code = read(results / "code_gen.jsonl")
    assert [row["result"]["passed"] for row in code] == [True, False]
    assert "judge_score" not in code[0]["result"]
    assert code[1]["output"]["code"].startswith("echo:")


def test_selected_tasks_need_no_other_inputs(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config),
        "--input", f"mmlu={data / 'mmlu.jsonl'}",
        "--output", str(results),
        "--task", "mmlu",
    )

    assert completed.returncode == 0, completed.stderr
    assert set(json.loads(completed.stdout)["tasks"]) == {"mmlu"}
    assert (results / "mmlu.jsonl").exists()
    assert not (results / "review.jsonl").exists()


def test_missing_input_mapping_is_an_error(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config),
        "--input", f"mmlu={data / 'mmlu.jsonl'}",
        "--output", str(results),
    )

    assert completed.returncode == 1
    assert "review" in completed.stderr and "code_gen" in completed.stderr


def test_input_and_input_dir_cannot_be_combined(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config),
        "--input", f"mmlu={data / 'mmlu.jsonl'}",
        "--input-dir", str(data),
        "--output", str(results),
    )

    assert completed.returncode == 1
    assert "--input-dir" in completed.stderr


def test_unmapped_input_for_a_multi_task_config_is_an_error(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config),
        "--input", str(data / "mmlu.jsonl"),
        "--output", str(results),
        "--task", "mmlu",
    )

    assert completed.returncode == 1
    assert "<task>=<path>" in completed.stderr


def test_unknown_task_name_is_an_error(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config), "--input-dir", str(data), "--output", str(results), "--task", "gsm8k"
    )

    assert completed.returncode == 1
    assert "gsm8k" in completed.stderr


def test_defaults_are_merged_into_every_task(mock_server, workspace, run_rejector):
    server = mock_server()
    config, data, results = workspace(server.url)

    completed = run_rejector(
        "--config", str(config), "--input-dir", str(data), "--output", str(results), "--task", "mmlu"
    )

    assert completed.returncode == 0, completed.stderr
    assert read(results / "mmlu.jsonl")[0]["meta"]["model"] == "mock-model"

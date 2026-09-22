"""End-to-end tests for in-context learning setups and multi-solution runs."""

import json

import yaml

COT = {
    "name": "chain_of_thought",
    "examples": [
        {"input": {"question": "What is 2+2?"}, "output": "Let me think step by step.\n2 + 2 = 4\n#### 4"},
        {"input": {"question": "3 cats and 2 more?"}, "output": "Step by step:\n3 + 2 = 5\n#### 5"},
    ],
}
DIRECT = {"name": "direct", "examples": [{"input": {"question": "What is 2+2?"}, "output": "#### 4"}]}
TERSE = {"name": "terse", "examples": [{"input": {"question": "What is 2+2?"}, "output": "4"}]}

ROWS = [{"question": "two plus six?", "answer": "8"}]

EVALUATION = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}


def config(url, *, icl=None, evaluation=EVALUATION, **task):
    """Build a single-task YAML config pointed at the mock server."""
    document = {
        "task": {
            "name": "mock_task",
            "api_url": url,
            "model": "mock-model",
            "rpm": 600,
            "prompt": {"system": "Solve the problem. Final answer after ####.", "user": "{question}"},
            "generation": {"scheme": "greedy", "temperature": 0.0, "max_tokens": 64, "n": 1},
            "output_field": "solution",
            **task,
        }
    }
    if icl is not None:
        document["task"]["icl"] = icl
    if evaluation is not None:
        document["task"]["evaluation"] = evaluation
    return yaml.safe_dump(document)


def setups_used(result):
    return [item["icl_setup"] for item in result["output"]]


def test_icl_turns_are_sent_and_recorded(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT], "strategy": "fixed"}

    completed, summary, results = run_cli(config(server.url, icl=icl), ROWS)

    assert completed.returncode == 0, completed.stderr
    solution = results[0]["output"][0]
    assert setups_used(results[0]) == ["chain_of_thought"]
    # system + two user/assistant example turns + the row's own question
    assert "turns=6" in solution["solution"]
    assert results[0]["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert results[0]["meta"][0]["icl_setup"] == "chain_of_thought"
    assert results[0]["meta"][0]["evaluation_passed"] is True
    assert summary["passed"] == 1


def test_icl_k_keeps_the_first_examples(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT], "k": 1}

    _, _, results = run_cli(config(server.url, icl=icl), ROWS)

    assert "turns=4" in results[0]["output"][0]["solution"]


def test_round_robin_cycles_setups_across_attempts(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT, DIRECT, TERSE], "strategy": "round_robin"}
    task = {"generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}, "num_solutions": 5}

    _, _, results = run_cli(config(server.url, icl=icl, **task), ROWS)

    assert setups_used(results[0]) == ["chain_of_thought", "direct", "terse", "chain_of_thought", "direct"]
    assert results[0]["result"]["attempts"] == 5


def test_fixed_strategy_always_uses_the_first_setup(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT, DIRECT], "strategy": "fixed"}
    task = {"generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}, "num_solutions": 3}

    _, _, results = run_cli(config(server.url, icl=icl, **task), ROWS)

    assert setups_used(results[0]) == ["chain_of_thought"] * 3


def test_random_strategy_picks_configured_setups(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT, DIRECT, TERSE], "strategy": "random"}
    task = {"generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}, "num_solutions": 6}

    _, _, results = run_cli(config(server.url, icl=icl, **task), ROWS)

    assert set(setups_used(results[0])) <= {"chain_of_thought", "direct", "terse"}
    assert len(results[0]["output"]) == 6


def test_greedy_uses_each_setup_at_most_once(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT, DIRECT], "strategy": "round_robin"}

    _, _, results = run_cli(config(server.url, icl=icl, num_solutions=5), ROWS)

    assert setups_used(results[0]) == ["chain_of_thought", "direct"]
    assert results[0]["result"]["attempts"] == 2


def test_sample_without_icl_makes_one_request_per_solution(mock_server, run_cli):
    server = mock_server()
    task = {"generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}, "num_solutions": 3}

    _, summary, results = run_cli(config(server.url, **task), ROWS)

    assert setups_used(results[0]) == [None, None, None]
    assert results[0]["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert all(meta["icl_setup"] is None for meta in results[0]["meta"])
    assert summary["total_api_calls"] == 3


def test_rejection_collects_several_passing_solutions(mock_server, run_cli):
    server = mock_server("--pass-after", "2")
    task = {
        "generation": {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64, "max_attempts": 10},
        "num_solutions": 3,
    }

    _, _, results = run_cli(config(server.url, **task), ROWS)

    assert len(results[0]["output"]) == 3
    assert results[0]["result"] == {"passed": 3, "failed": 2, "attempts": 5}
    assert [meta["evaluation_passed"] for meta in results[0]["meta"]] == [False, False, True, True, True]


def test_rejection_writes_the_solutions_it_managed_to_collect(mock_server, run_cli):
    server = mock_server("--pass-every", "5")
    task = {
        "generation": {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64, "max_attempts": 10},
        "num_solutions": 5,
    }

    _, summary, results = run_cli(config(server.url, **task), ROWS)

    assert len(results[0]["output"]) == 2
    assert results[0]["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert summary["passed"] == 1


def test_rejection_defaults_max_attempts_to_three_per_solution(mock_server, run_cli):
    server = mock_server("--pass-after", "100")
    task = {
        "generation": {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64},
        "num_solutions": 2,
    }

    _, summary, results = run_cli(config(server.url, **task), ROWS)

    assert results[0]["output"] == []
    assert results[0]["result"] == {"passed": 0, "failed": 6, "attempts": 6}
    assert summary["failed"] == 1


def test_list_format_without_evaluation_counts_emitted_outputs(mock_server, run_cli):
    server = mock_server()
    task = {"generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}, "num_solutions": 2}

    _, _, results = run_cli(config(server.url, evaluation=None, **task), ROWS)

    assert results[0]["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert all(meta["evaluation_passed"] is None for meta in results[0]["meta"])


def test_single_solution_without_icl_keeps_the_part_1_format(mock_server, run_cli):
    server = mock_server()

    _, _, results = run_cli(config(server.url), ROWS)

    assert list(results[0]["output"]) == ["solution"]
    assert results[0]["result"] == {"passed": True, "extracted_answer": "8", "attempts": 1}
    assert results[0]["meta"]["model"] == "mock-model"


def test_cli_flags_override_the_configured_icl_settings(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [COT, DIRECT], "strategy": "fixed"}
    task = {"generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}}

    _, _, results = run_cli(
        config(server.url, icl=icl, **task), ROWS,
        "--num-solutions", "2", "--icl-strategy", "round_robin", "--icl-k", "1",
    )

    assert setups_used(results[0]) == ["chain_of_thought", "direct"]
    assert "turns=4" in results[0]["output"][0]["solution"]


def test_file_backed_setup_is_loaded_relative_to_the_config(mock_server, run_cli, tmp_path):
    server = mock_server()
    examples = tmp_path / "icl"
    examples.mkdir()
    (examples / "detailed.jsonl").write_text(
        '{"input": {"question": "What is 10 / 2?"}, "output": "10 divided by 2 is 5.\\n#### 5"}\n'
        "\n"
        '{"input": {"question": "What is 1 + 1?"}, "output": "#### 2"}\n',
        encoding="utf-8",
    )
    icl = {"setups": [{"name": "detailed", "file": "icl/detailed.jsonl"}], "k": 3}

    completed, _, results = run_cli(config(server.url, icl=icl), ROWS)

    assert completed.returncode == 0, completed.stderr
    assert setups_used(results[0]) == ["detailed"]
    assert "turns=6" in results[0]["output"][0]["solution"]


def test_malformed_icl_file_stops_the_run(mock_server, run_cli, tmp_path):
    server = mock_server()
    (tmp_path / "examples.jsonl").write_text(
        '{"input": {"question": "What is 1 + 1?"}, "output": "#### 2"}\nnot json\n', encoding="utf-8"
    )
    icl = {"setups": [{"name": "detailed", "file": "examples.jsonl"}]}

    completed, _, results = run_cli(config(server.url, icl=icl), ROWS)

    assert completed.returncode == 1
    assert "not valid JSON" in completed.stderr and "line 2" in completed.stderr
    assert results == []


def test_icl_example_missing_output_stops_the_run(mock_server, run_cli, tmp_path):
    server = mock_server()
    (tmp_path / "examples.jsonl").write_text('{"input": {"question": "What is 1 + 1?"}}\n', encoding="utf-8")
    icl = {"setups": [{"name": "detailed", "file": "examples.jsonl"}]}

    completed, _, _ = run_cli(config(server.url, icl=icl), ROWS)

    assert completed.returncode == 1
    assert "'output'" in completed.stderr


def test_setup_needs_exactly_one_example_source(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [{"name": "both", "file": "a.jsonl", "examples": DIRECT["examples"]}]}

    completed, _, _ = run_cli(config(server.url, icl=icl), ROWS)

    assert completed.returncode == 1
    assert "exactly one of 'examples' or 'file'" in completed.stderr


def test_unknown_icl_strategy_is_a_config_error(mock_server, run_cli):
    server = mock_server()

    completed, _, _ = run_cli(config(server.url, icl={"setups": [COT]}), ROWS, "--icl-strategy", "shuffle")

    assert completed.returncode == 1
    assert "strategy" in completed.stderr


def test_icl_example_missing_a_prompt_field_stops_the_run(mock_server, run_cli):
    server = mock_server()
    icl = {"setups": [{"name": "typo", "examples": [{"input": {"q": "What is 2+2?"}, "output": "#### 4"}]}]}

    completed, _, _ = run_cli(config(server.url, icl=icl), ROWS)

    assert completed.returncode == 1
    assert "icl setup 'typo' example 0" in completed.stderr and "question" in completed.stderr


def test_per_task_summary_reports_solution_counts(mock_server, run_rejector, tmp_path):
    server = mock_server()
    document = {
        "defaults": {"api_url": server.url, "model": "mock-model", "rpm": 600},
        "tasks": {
            "gsm8k": {
                "prompt": {"system": "Solve it.", "user": "{question}"},
                "generation": {"scheme": "sample", "temperature": 0.7, "max_tokens": 64},
                "evaluation": EVALUATION,
                "icl": {"setups": [COT, DIRECT], "strategy": "round_robin"},
                "num_solutions": 3,
                "output_field": "solution",
            }
        },
    }
    config_path = tmp_path / "multi.yaml"
    config_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    rows = [{"question": f"row {index}?", "answer": "8"} for index in range(4)]
    (data / "gsm8k.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    completed = run_rejector(
        "--config", str(config_path), "--input-dir", str(data), "--output", str(tmp_path / "out")
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["tasks"]["gsm8k"] == {
        "total": 4,
        "passed": 4,
        "failed": 0,
        "total_solutions": 12,
        "avg_solutions_per_input": 3.0,
        "total_api_calls": 12,
    }

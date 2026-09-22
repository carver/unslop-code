"""End-to-end CLI runs of ICL setups and of tasks asking for several solutions."""

import json

import yaml
from conftest import read_results, run_cli, write_jsonl

ROWS = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(3)]

#: Each setup's single example answers with its own name, which the mock server
#: echoes back as `ICL=1:<name>`, so a solution shows the setup that produced it.
SETUPS = [
    {"name": name, "examples": [{"input": {"question": "demo"}, "output": name}]}
    for name in ("a", "b", "c")
]


def write_task(tmp_path, api_url, icl=None, evaluation="default", **changes):
    task = {
        "name": "mock_task",
        "api_url": api_url,
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {"system": "Solve it. Answer after ####.", "user": "{question}"},
        "generation": {"scheme": "greedy", "max_tokens": 64},
        "output_field": "solution",
        **changes,
    }
    if evaluation == "default":
        evaluation = {"type": "exact_match", "answer_field": "answer", "extract": "last_number"}
    if evaluation is not None:
        task["evaluation"] = evaluation
    if icl is not None:
        task["icl"] = icl
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump({"task": task}))
    return path


def run_task(tmp_path, config, *extra, rows=ROWS):
    output = tmp_path / "out.jsonl"
    data = write_jsonl(tmp_path / "data.jsonl", rows)
    process = run_cli("--config", config, "--input", data, "--output", output, *extra)
    return process, output


def setup_names(record):
    return [item["icl_setup"] for item in record["output"]]


def test_a_single_solution_icl_run_uses_the_list_format(tmp_path, server):
    config = write_task(tmp_path, server(), icl={"setups": SETUPS[:1]})
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["output"] == [{"solution": "Working it out.\nICL=1:a\n#### 1", "icl_setup": "a"}]
    assert record["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert len(record["meta"]) == 1
    assert record["meta"][0]["evaluation_passed"] is True
    assert record["meta"][0]["icl_setup"] == "a"
    assert record["meta"][0]["model"] == "gpt-4"


def test_no_icl_and_one_solution_keeps_the_part_1_format(tmp_path, server):
    process, output = run_task(tmp_path, write_task(tmp_path, server()))

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["output"] == {"solution": "Working it out.\n#### 1"}
    assert record["result"] == {"passed": True, "extracted_answer": "1", "attempts": 1}
    assert isinstance(record["meta"], dict)


def test_round_robin_cycles_the_setups_across_attempts(tmp_path, server):
    icl = {"setups": SETUPS, "strategy": "round_robin"}
    generation = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server(), icl=icl, generation=generation, num_solutions=5)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert setup_names(record) == ["a", "b", "c", "a", "b"]
    assert [meta["icl_setup"] for meta in record["meta"]] == ["a", "b", "c", "a", "b"]
    assert "ICL=1:c" in record["output"][2]["solution"], "the setup's example reached the server"


def test_fixed_keeps_the_first_setup_for_every_attempt(tmp_path, server):
    icl = {"setups": SETUPS, "strategy": "fixed"}
    generation = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server(), icl=icl, generation=generation, num_solutions=3)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    assert setup_names(read_results(output)[0]) == ["a", "a", "a"]


def test_sample_does_not_gate_solutions_on_the_evaluation(tmp_path, server):
    """The row's answer never matches, yet every sampled solution is written."""
    generation = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server("--pass-after", "99"), generation=generation,
                        num_solutions=4)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert len(record["output"]) == 4
    assert setup_names(record) == [None] * 4, "no ICL means a null setup name"
    assert record["result"] == {"passed": 0, "failed": 4, "attempts": 4}
    assert all(meta["evaluation_passed"] is False for meta in record["meta"])


def test_greedy_produces_at_most_one_solution_per_setup(tmp_path, server):
    config = write_task(tmp_path, server(), icl={"setups": SETUPS[:2]}, num_solutions=5)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert setup_names(record) == ["a", "b"], "the two setups are each used once"
    assert record["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert json.loads(process.stdout)["total_api_calls"] == 2 * len(ROWS)


def test_greedy_walks_setups_in_order_whatever_the_strategy(tmp_path, server):
    icl = {"setups": SETUPS, "strategy": "random"}
    config = write_task(tmp_path, server(), icl=icl, num_solutions=2)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    assert all(setup_names(record) == ["a", "b"] for record in read_results(output))


def test_rejection_collects_several_passing_solutions(tmp_path, server):
    generation = {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64, "max_attempts": 10}
    config = write_task(tmp_path, server("--pass-after", "3"), generation=generation,
                        num_solutions=2)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"] == {"passed": 2, "failed": 2, "attempts": 4}
    assert [item["solution"] for item in record["output"]] == ["Working it out.\n#### 1"] * 2
    assert len(record["meta"]) == 4
    assert [meta["evaluation_passed"] for meta in record["meta"]] == [False, False, True, True]


def test_rejection_writes_the_solutions_it_managed_to_collect(tmp_path, server):
    """Five wanted, ten attempts allowed, and only every fifth attempt passes."""
    generation = {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64, "max_attempts": 10}
    config = write_task(tmp_path, server("--pass-every", "5"), generation=generation,
                        num_solutions=5)
    process, output = run_task(tmp_path, config, rows=ROWS[:1])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert len(record["output"]) == 2
    assert len(record["meta"]) == 10


def test_rejection_defaults_its_budget_to_three_attempts_per_solution(tmp_path, server):
    generation = {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server("--pass-after", "99"), generation=generation,
                        num_solutions=2)
    process, output = run_task(tmp_path, config, rows=ROWS[:1])

    assert process.returncode == 0, process.stderr
    assert read_results(output)[0]["result"] == {"passed": 0, "failed": 6, "attempts": 6}


def test_rejection_without_icl_repeats_the_same_prompt(tmp_path, server):
    generation = {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server(), generation=generation, num_solutions=2)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert setup_names(record) == [None, None]
    assert all("ICL=" not in item["solution"] for item in record["output"])


def test_a_single_solution_rejection_run_keeps_the_part_1_budget(tmp_path, server):
    """`n` still bounds the attempts, and `max_attempts` is not applied."""
    generation = {"scheme": "rejection", "temperature": 0.7, "max_tokens": 64,
                  "n": 2, "max_attempts": 10}
    config = write_task(tmp_path, server("--pass-after", "9"), generation=generation)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["output"] is None
    assert record["result"] == {"passed": False, "extracted_answer": None, "attempts": 2}


def test_a_run_without_evaluation_counts_the_emitted_outputs(tmp_path, server):
    generation = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server(), evaluation=None, generation=generation,
                        num_solutions=3)
    process, output = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert all(meta["evaluation_passed"] is None for meta in record["meta"])


def test_unanswered_attempts_count_as_failures(tmp_path, server):
    generation = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server("--always-500"), evaluation=None, generation=generation,
                        num_solutions=2)
    process, output = run_task(tmp_path, config, rows=ROWS[:1])

    assert process.returncode == 0, process.stderr
    record = read_results(output)[0]
    assert record["output"] == []
    assert record["meta"] == []
    assert record["result"] == {"passed": 0, "failed": 2, "attempts": 2}


def test_cli_flags_override_the_configured_setup_choice(tmp_path, server):
    icl = {"setups": SETUPS, "strategy": "fixed", "k": 1}
    generation = {"scheme": "sample", "temperature": 0.7, "max_tokens": 64}
    config = write_task(tmp_path, server(), icl=icl, generation=generation)
    process, output = run_task(tmp_path, config, "--num-solutions", "4",
                               "--icl-strategy", "round_robin")

    assert process.returncode == 0, process.stderr
    assert setup_names(read_results(output)[0]) == ["a", "b", "c", "a"]


def test_icl_k_limits_the_examples_sent(tmp_path, server):
    examples = [{"input": {"question": f"demo {index}"}, "output": f"answer {index}"}
                for index in range(3)]
    icl = {"setups": [{"name": "detailed", "examples": examples}]}
    process, output = run_task(tmp_path, write_task(tmp_path, server(), icl=icl), "--icl-k", "2")

    assert process.returncode == 0, process.stderr
    assert "ICL=2:answer 0" in read_results(output)[0]["output"][0]["solution"]


def test_summary_reports_the_solutions_each_task_produced(tmp_path, server):
    config = write_task(tmp_path, server(), icl={"setups": SETUPS}, num_solutions=3)
    process, _ = run_task(tmp_path, config)

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["total"] == len(ROWS)
    assert summary["passed"] == len(ROWS)
    assert summary["total_solutions"] == 3 * len(ROWS)
    assert summary["avg_solutions_per_input"] == 3.0
    assert summary["total_api_calls"] == 3 * len(ROWS)


def test_a_malformed_example_file_stops_the_run_before_any_request(tmp_path, server):
    directory = tmp_path / "icl"
    directory.mkdir()
    (directory / "broken.jsonl").write_text('{"input": {"question": "q"}, "output": 5}\n')
    icl = {"setups": [{"name": "detailed", "file": "icl/broken.jsonl"}]}
    process, output = run_task(tmp_path, write_task(tmp_path, server(), icl=icl))

    assert process.returncode == 1
    assert "output" in process.stderr
    assert not output.exists()


def test_an_example_missing_a_template_field_stops_the_run(tmp_path, server):
    icl = {"setups": [{"name": "d", "examples": [{"input": {"other": "x"}, "output": "#### 4"}]}]}
    process, output = run_task(tmp_path, write_task(tmp_path, server(), icl=icl))

    assert process.returncode == 1
    assert "missing field 'question'" in process.stderr
    assert not output.exists()


def test_a_single_greedy_solution_still_follows_the_strategy(tmp_path, server):
    """Only a greedy run wanting several solutions overrides the strategy."""
    rows = [{"question": f"Row {i}: compute ANSWER={i + 1}", "answer": str(i + 1)} for i in range(20)]
    icl = {"setups": SETUPS, "strategy": "random"}
    process, output = run_task(tmp_path, write_task(tmp_path, server(), icl=icl), rows=rows)

    assert process.returncode == 0, process.stderr
    chosen = {setup_names(record)[0] for record in read_results(output)}
    assert chosen <= {"a", "b", "c"}
    assert len(chosen) > 1, "20 rows drawing at random should not all land on one setup"

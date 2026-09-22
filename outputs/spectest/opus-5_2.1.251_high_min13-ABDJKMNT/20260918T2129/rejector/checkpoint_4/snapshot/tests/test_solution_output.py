"""The multi-solution row format and the solution counts in the summary."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, always, completion
from conftest import GSM8K_TASK, base_config, icl_config, icl_setup, multi_config

ROW = {"question": "What is 15 + 27?", "answer": "42"}
PASS = "#### 42"
FAIL = "#### 0"

META_KEYS = {
    "model", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason",
    "icl_setup", "evaluation_passed",
}


def _passes_on(*indices):
    """Responder whose attempts at `indices` pass exact_match; the rest fail."""

    def responder(payload, index):
        return Reply(completion(PASS if index in indices else FAIL))

    return responder


def _run(write_config, write_input, run_cli, config_map, *extra, responder=None, rows=None):
    with FakeAPIServer(responder or always(PASS)) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
    return result


def _sampling(config_map, num_solutions, **generation):
    config_map["task"]["generation"] = {
        "scheme": "sample", "temperature": 0.7, "max_tokens": 64, **generation
    }
    config_map["task"]["num_solutions"] = num_solutions
    return config_map


def _rejection(config_map, num_solutions, **generation):
    config_map["task"]["generation"] = {
        "scheme": "rejection", "temperature": 0.7, "max_tokens": 64, **generation
    }
    config_map["task"]["num_solutions"] = num_solutions
    return config_map


# Spec: "output becomes a list of objects, each containing the task's
# output_field plus icl_setup"
def test_output_items_carry_the_output_field_and_setup(write_config, write_input, run_cli):
    setups = [icl_setup("chain_of_thought", "cot-1"), icl_setup("direct", "direct-1")]
    config_map = icl_config("", setups, strategy="round_robin")
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 2))

    row = result.rows[0]
    assert row["input"] == ROW
    assert row["output"] == [
        {"solution": PASS, "icl_setup": "chain_of_thought"},
        {"solution": PASS, "icl_setup": "direct"},
    ]


# Spec: "icl_setup is ... null when no ICL is configured"
def test_icl_setup_is_null_without_icl(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _sampling(base_config(""), 2))
    assert result.rows[0]["output"] == [
        {"solution": PASS, "icl_setup": None},
        {"solution": PASS, "icl_setup": None},
    ]


# Spec: "result.passed is the count of passing solutions", "result.failed is
# the count of failed attempts", "result.attempts is the total number of
# generation attempts for the row"
def test_result_counts_passes_failures_and_attempts(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1")])
    result = _run(
        write_config,
        write_input,
        run_cli,
        _rejection(config_map, 2, max_attempts=7),
        responder=_passes_on(1, 6),
    )

    row = result.rows[0]
    assert row["result"] == {"passed": 2, "failed": 5, "attempts": 7}


# Spec: "meta is a list with one entry per attempt" and "each metadata entry
# includes icl_setup and evaluation_passed"
def test_meta_has_one_entry_per_attempt_with_the_new_keys(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1")])
    result = _run(
        write_config, write_input, run_cli, _sampling(config_map, 3), responder=_passes_on(0)
    )

    metas = result.rows[0]["meta"]
    assert isinstance(metas, list)
    assert len(metas) == 3
    assert all(set(meta) == META_KEYS for meta in metas)
    assert [meta["evaluation_passed"] for meta in metas] == [True, False, False]
    assert [meta["icl_setup"] for meta in metas] == ["A", "A", "A"]


# Spec: "if evaluation is omitted in list format, evaluation_passed is null
# for each metadata entry, result.passed is the number of emitted outputs"
def test_without_evaluation_passed_counts_emitted_outputs(write_config, write_input, run_cli):
    config_map = base_config("")
    del config_map["task"]["evaluation"]
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 3))

    row = result.rows[0]
    assert row["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert [meta["evaluation_passed"] for meta in row["meta"]] == [None, None, None]


# Spec: "result.failed is the number of attempts that produced no output"
# when evaluation is omitted (see AMBIGUITIES T41)
def test_attempts_without_output_count_as_failed(write_config, write_input, run_cli):
    def responder(payload, index):
        return Reply("rejected", status=400) if index == 1 else Reply(completion(PASS))

    config_map = base_config("")
    del config_map["task"]["evaluation"]
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 3), responder=responder)

    row = result.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert len(row["meta"]) == 2


# Spec: "when num_solutions == 1 and no ICL is configured, keep the Part 1
# output format"
def test_single_solution_without_icl_keeps_the_part_one_format(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, base_config(""))

    row = result.rows[0]
    assert row["output"] == {"solution": PASS}
    assert row["result"] == {"passed": True, "extracted_answer": "42", "attempts": 1}
    assert isinstance(row["meta"], dict)


# Spec: "when ICL is configured, use the list format even if
# num_solutions == 1" - the single-solution ICL example
def test_single_solution_with_icl_uses_the_list_format(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("chain_of_thought", "cot-1")])
    config_map["task"]["num_solutions"] = 1
    result = _run(write_config, write_input, run_cli, config_map)

    row = result.rows[0]
    assert row["output"] == [{"solution": PASS, "icl_setup": "chain_of_thought"}]
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert isinstance(row["meta"], list)
    assert row["meta"][0]["evaluation_passed"] is True
    assert row["meta"][0]["icl_setup"] == "chain_of_thought"


# Spec: the worked rejection partial result - num_solutions 5, max_attempts
# 10, two passes: "write only those two passing outputs", "passed: 2,
# failed: 8, attempts: 10"
def test_rejection_partial_result_reports_the_worked_example(write_config, write_input, run_cli):
    config_map = _rejection(base_config(""), 5, max_attempts=10)
    result = _run(write_config, write_input, run_cli, config_map, responder=_passes_on(0, 3))

    row = result.rows[0]
    assert len(result.payloads) == 10
    assert row["output"] == [
        {"solution": PASS, "icl_setup": None},
        {"solution": PASS, "icl_setup": None},
    ]
    assert row["result"] == {"passed": 2, "failed": 8, "attempts": 10}
    assert len(row["meta"]) == 10


# Spec: rejection keeps only passing solutions, so a run with none writes an
# empty list (see AMBIGUITIES T40)
def test_rejection_without_any_pass_writes_an_empty_output_list(write_config, write_input, run_cli):
    config_map = _rejection(base_config(""), 2, max_attempts=3)
    result = _run(write_config, write_input, run_cli, config_map, responder=always(FAIL))

    row = result.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# Spec: "Per-task summary fields gain: total_solutions,
# avg_solutions_per_input, total_api_calls"
def test_per_task_summary_reports_solution_counts(write_config, write_input, run_argv):
    gsm8k = {**GSM8K_TASK, "generation": {"scheme": "sample", "temperature": 0.7}, "num_solutions": 3}
    rows = [ROW, {"question": "q2", "answer": "42"}]
    with FakeAPIServer(always(PASS)) as api:
        config = write_config(multi_config(api.url, {"gsm8k": gsm8k}))
        result = run_argv("--config", config, "--input", f"gsm8k={write_input(rows, name='m.jsonl')}")

    task_summary = result.summary["tasks"]["gsm8k"]
    assert task_summary["total"] == 2
    assert task_summary["total_solutions"] == 6
    assert task_summary["avg_solutions_per_input"] == 3.0
    assert task_summary["total_api_calls"] == 6


# Spec: per-task "passed"/"failed" still count rows; a row passes when it
# collected at least one passing solution (see AMBIGUITIES T44)
def test_per_task_row_counts_follow_passing_solutions(write_config, write_input, run_argv):
    gsm8k = {
        **GSM8K_TASK,
        "generation": {"scheme": "sample", "temperature": 0.7},
        "num_solutions": 2,
    }

    def responder(payload, index):
        good = "good" in payload["messages"][-1]["content"]
        return Reply(completion(PASS if good else FAIL))

    rows = [{"question": "good", "answer": "42"}, {"question": "bad", "answer": "42"}]
    with FakeAPIServer(responder) as api:
        config = write_config(multi_config(api.url, {"gsm8k": gsm8k}))
        result = run_argv("--config", config, "--input", f"gsm8k={write_input(rows, name='m.jsonl')}")

    task_summary = result.summary["tasks"]["gsm8k"]
    assert (task_summary["passed"], task_summary["failed"]) == (1, 1)
    assert task_summary["total_solutions"] == 4


# Spec: the summary printed on stdout keeps its documented top-level keys
# (see AMBIGUITIES T43)
def test_top_level_summary_keys_are_unchanged(write_config, write_input, run_cli):
    result = _run(write_config, write_input, run_cli, _sampling(base_config(""), 2))
    assert set(result.summary) == {
        "total", "passed", "failed", "total_prompt_tokens", "total_completion_tokens",
        "total_api_calls", "elapsed_seconds", "throughput_rpm",
    }

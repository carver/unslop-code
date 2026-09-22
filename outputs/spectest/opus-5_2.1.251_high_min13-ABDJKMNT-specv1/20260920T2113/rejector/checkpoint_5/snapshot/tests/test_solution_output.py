"""The list output format for ICL and multi-solution rows, and the summary."""

from __future__ import annotations

from tests.conftest import icl_section, multi_config, task_config
from tests.fake_api import error, ok

ROW = {"question": "What is 15 + 27?", "answer": "42"}
META_KEYS = {
    "model", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms",
    "finish_reason", "icl_setup", "evaluation_passed",
}


def sampled(server, solutions: int, **overrides) -> dict:
    return task_config(
        api_url=server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=solutions,
        **overrides,
    )


# "If ICL is configured or num_solutions > 1, the per-row output format changes"
# '"output": [{"solution": ..., "icl_setup": "chain_of_thought"}, ...]'
def test_output_is_a_list_of_solutions_with_their_setup(cli, api):
    def responder(index, body):
        return ok("15 + 27 = 42\n#### 42") if index == 0 else ok("#### 42")

    server = api(responder)
    config = task_config(api_url=server.url, icl=icl_section("cot", "direct"), num_solutions=2)
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] == [
        {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "cot"},
        {"solution": "#### 42", "icl_setup": "direct"},
    ]


# "`output` becomes a list of objects, each containing the task's `output_field`
#  plus `icl_setup`"
def test_solution_objects_use_the_task_output_field(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(sampled(server, 2, output_field="completion"), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] == [{"completion": "#### 42", "icl_setup": None}] * 2


# "when ICL is configured, use the list format even if `num_solutions == 1`"
# "with num_solutions: 1 and ICL enabled, output is still a list" / "the single
#  output item records the chosen icl_setup" / "meta is also a list and includes
#  evaluation_passed"
def test_single_solution_icl_row_still_uses_the_list_format(cli, static_api):
    server = static_api("#### 42")
    config = task_config(api_url=server.url, icl=icl_section("cot"), num_solutions=1)
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == [{"solution": "#### 42", "icl_setup": "cot"}]
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert isinstance(row["meta"], list) and len(row["meta"]) == 1
    assert row["meta"][0]["evaluation_passed"] is True


# "If ICL is configured or `num_solutions > 1`" - num_solutions alone is enough
def test_multi_solution_row_without_icl_uses_the_list_format(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(sampled(server, 2), [ROW])
    assert run.returncode == 0, run.stderr
    assert isinstance(run.rows[0]["output"], list)
    assert isinstance(run.rows[0]["meta"], list)


# "when `num_solutions == 1` and no ICL is configured, keep the Part 1 output
#  format"
def test_legacy_row_format_is_unchanged(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(task_config(api_url=server.url), [ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"] == {"passed": True, "extracted_answer": "42", "attempts": 1}
    assert isinstance(row["meta"], dict)
    assert "icl_setup" not in row["meta"]


# "`result.passed` is the count of passing solutions" / "`result.failed` is the
#  count of failed attempts" / "`result.attempts` is the total number of
#  generation attempts for the row"
def test_result_counts_passing_solutions_and_failed_attempts(cli, api):
    server = api(lambda index, body: ok("#### 42") if index < 2 else ok("#### 7"))
    run = cli.run(sampled(server, 5), [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"] == {"passed": 2, "failed": 3, "attempts": 5}


# T38: the list format's `result` holds exactly the three documented counts
def test_result_holds_only_the_documented_counts(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(sampled(server, 2), [ROW])
    assert run.returncode == 0, run.stderr
    assert set(run.rows[0]["result"]) == {"passed", "failed", "attempts"}


# "`meta` is a list with one entry per attempt" / "each metadata entry includes
#  `icl_setup` and `evaluation_passed`"
def test_meta_has_one_entry_per_attempt_with_setup_and_verdict(cli, api):
    server = api(lambda index, body: ok("#### 42") if index == 0 else ok("#### 7"))
    config = task_config(
        api_url=server.url,
        generation={"scheme": "sample", "temperature": 0.7},
        icl=icl_section("cot", "direct", strategy="round_robin"),
        num_solutions=2,
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert [set(entry) for entry in meta] == [META_KEYS, META_KEYS]
    assert [entry["icl_setup"] for entry in meta] == ["cot", "direct"]
    assert [entry["evaluation_passed"] for entry in meta] == [True, False]
    assert meta[0]["total_tokens"] == 15


# "if evaluation is omitted in list format, `evaluation_passed` is `null` for
#  each metadata entry, `result.passed` is the number of emitted outputs, and
#  `result.failed` is the number of attempts that produced no output"
def test_list_format_without_evaluation(cli, api):
    # The first attempt burns its three HTTP requests and so emits no output.
    server = api(lambda index, body: error(500) if index < 3 else ok("anything"))
    config = sampled(server, 3)
    config["task"].pop("evaluation")
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert [entry["evaluation_passed"] for entry in row["meta"]] == [None, None, None]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# "`icl_setup` is the chosen setup name, or `null` when no ICL is configured"
def test_icl_setup_is_null_without_icl(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(sampled(server, 2), [ROW])
    assert run.returncode == 0, run.stderr
    assert [item["icl_setup"] for item in run.rows[0]["output"]] == [None, None]
    assert [entry["icl_setup"] for entry in run.rows[0]["meta"]] == [None, None]


# "write only those two passing outputs" - failed attempts leave no output item
def test_failed_attempts_are_absent_from_the_output_list(cli, api):
    server = api(lambda index, body: ok("#### 42") if index == 1 else ok("#### 7"))
    config = task_config(
        api_url=server.url,
        generation={"scheme": "rejection", "temperature": 0.7, "max_attempts": 4},
        num_solutions=3,
    )
    run = cli.run(config, [ROW])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] == [{"solution": "#### 42", "icl_setup": None}]
    assert len(run.rows[0]["meta"]) == 4


# "input is the original row, unchanged" still holds in the list format
def test_row_keeps_input_and_the_four_documented_keys(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(sampled(server, 2), [ROW])
    assert run.returncode == 0, run.stderr
    assert set(run.rows[0]) == {"input", "output", "result", "meta"}
    assert run.rows[0]["input"] == ROW


# '"total_solutions": 450, "avg_solutions_per_input": 4.5, "total_api_calls"'
def test_per_task_summary_reports_solution_counts(cli, static_api):
    server = static_api("#### 5")
    config = multi_config("gsm8k", defaults={"api_url": server.url, "num_solutions": 2})
    config["tasks"]["gsm8k"]["generation"] = {
        "scheme": "sample", "temperature": 0.7,
    }
    run = cli.run_multi(config, {"gsm8k": [{"question": "q", "answer": "5"}] * 3})
    assert run.returncode == 0, run.stderr
    task = run.summary["tasks"]["gsm8k"]
    assert task["total"] == 3
    assert task["total_solutions"] == 6
    assert task["avg_solutions_per_input"] == 2.0
    assert task["total_api_calls"] == 6


# T42: a row counts as passed for the summary when it produced a passing solution
def test_summary_counts_rows_with_at_least_one_passing_solution(cli, api):
    def responder(index, body):
        return ok("#### 5") if body["messages"][-1]["content"] == "0" else ok("#### 9")

    server = api(responder)
    config = multi_config("gsm8k", defaults={"api_url": server.url, "num_solutions": 2})
    config["tasks"]["gsm8k"]["generation"] = {
        "scheme": "rejection", "temperature": 0.7, "max_attempts": 2,
    }
    rows = [{"question": str(index), "answer": "5"} for index in range(2)]
    run = cli.run_multi(config, {"gsm8k": rows})
    assert run.returncode == 0, run.stderr
    assert run.summary["tasks"]["gsm8k"]["passed"] == 1
    assert run.summary["tasks"]["gsm8k"]["failed"] == 1
    assert run.summary["tasks"]["gsm8k"]["total_solutions"] == 2


# T43: a Part 1 single-task summary keeps exactly its Part 1 fields
def test_single_task_summary_keys_are_unchanged(cli, static_api):
    server = static_api("#### 42")
    run = cli.run(sampled(server, 2), [ROW])
    assert run.returncode == 0, run.stderr
    assert set(run.summary) == {
        "total", "passed", "failed", "total_prompt_tokens", "total_completion_tokens",
        "total_api_calls", "elapsed_seconds", "throughput_rpm",
    }

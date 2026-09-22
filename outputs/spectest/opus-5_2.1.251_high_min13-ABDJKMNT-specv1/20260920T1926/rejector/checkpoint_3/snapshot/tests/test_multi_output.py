"""The list output format, its `result` counters, `meta` list and summary."""

from __future__ import annotations

from conftest import (
    base_defaults,
    base_task,
    icl_block,
    inline_setup,
    math_task,
    task_rows,
)
from fake_api import FakeAPI, Reply, always, sequence

COT = inline_setup("chain_of_thought", "#### 4")
DIRECT = inline_setup("direct", "#### 4")

ROW = {"question": "What is 15 + 27?", "answer": "42"}


def multi_task(api_url: str, num_solutions: int, setups: list[dict] | None = None) -> dict:
    """A sampled task in the list output format."""
    task = base_task(api_url)
    task["generation"] = {"scheme": "sample", "temperature": 0.8}
    task["num_solutions"] = num_solutions
    if setups is not None:
        task["icl"] = icl_block(setups, strategy="round_robin")
    return task


# Spec: "`output` becomes a list of objects, each containing the task's
# `output_field` plus `icl_setup`"
# Context: Output Changes / Rules; the spec's example row.
def test_output_is_a_list_of_solution_objects(write_config, write_input, run_cli):
    script = [Reply(content="15 + 27 = 42\n#### 42"), Reply(content="#### 42")]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(multi_task(api.url, 2, [COT, DIRECT]))
        result = run_cli(config, write_input([ROW]))
    assert result.rows[0]["output"] == [
        {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
        {"solution": "#### 42", "icl_setup": "direct"},
    ]


# Spec: "`icl_setup` is the chosen setup name, or `null` when no ICL is
# configured"
# Context: Output Changes / Rules.
def test_icl_setup_is_null_without_icl(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 42")) as api:
        config = write_config(multi_task(api.url, 2))
        result = run_cli(config, write_input([ROW]))
    assert [item["icl_setup"] for item in result.rows[0]["output"]] == [None, None]


# Spec: "`result.passed` is the count of passing solutions" / "`result.failed`
# is the count of failed attempts" / "`result.attempts` is the total number of
# generation attempts for the row"
# Context: Output Changes / Rules.
def test_result_counts_passes_failures_and_attempts(write_config, write_input, run_cli):
    def responder(index, body):
        return Reply(content="#### 42" if index in (0, 3) else "#### 1")

    with FakeAPI(responder=responder) as api:
        config = write_config(multi_task(api.url, 5))
        result = run_cli(config, write_input([ROW]))
    assert result.rows[0]["result"] == {"passed": 2, "failed": 3, "attempts": 5}


# Spec: "`meta` is a list with one entry per attempt" / "each metadata entry
# includes `icl_setup` and `evaluation_passed`"
# Context: Output Changes / Rules.
def test_meta_is_a_list_with_setup_and_verdict(write_config, write_input, run_cli):
    script = [Reply(content="#### 42"), Reply(content="#### 1")]
    with FakeAPI(responder=sequence(script)) as api:
        config = write_config(multi_task(api.url, 2, [COT, DIRECT]))
        result = run_cli(config, write_input([ROW]))
    meta = result.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 2
    assert set(meta[0]) == {
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "icl_setup",
        "evaluation_passed",
    }
    assert [entry["icl_setup"] for entry in meta] == ["chain_of_thought", "direct"]
    assert [entry["evaluation_passed"] for entry in meta] == [True, False]


# Spec: "if evaluation is omitted in list format, `evaluation_passed` is `null`
# for each metadata entry, `result.passed` is the number of emitted outputs,
# and `result.failed` is the number of attempts that produced no output"
# Context: Output Changes / Rules.
def test_without_evaluation_passed_counts_emitted_outputs(
    write_config, write_input, run_cli
):
    script = [Reply(content="a")] + [Reply(status=500)] * 3 + [Reply(content="b")]
    with FakeAPI(responder=sequence(script)) as api:
        task = multi_task(api.url, 3)
        task.pop("evaluation")
        config = write_config(task)
        result = run_cli(config, write_input([{"question": "q"}]))
    row = result.rows[0]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert [entry["evaluation_passed"] for entry in row["meta"]] == [None, None]


# Spec: "when `num_solutions == 1` and no ICL is configured, keep the Part 1
# output format"
# Context: Output Changes / Rules.
def test_single_solution_without_icl_keeps_the_part_1_format(
    write_config, write_input, run_cli
):
    with FakeAPI(responder=always("#### 42")) as api:
        config = write_config(multi_task(api.url, 1))
        result = run_cli(config, write_input([ROW]))
    row = result.rows[0]
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"] == {"passed": True, "extracted_answer": "42", "attempts": 1}
    assert isinstance(row["meta"], dict)


# Spec: "when ICL is configured, use the list format even if
# `num_solutions == 1`" / "with `num_solutions: 1` and ICL enabled, `output` is
# still a list", "the single output item records the chosen `icl_setup`",
# "`meta` is also a list and includes `evaluation_passed`"
# Context: Output Changes / Examples (single-solution ICL run).
def test_single_solution_icl_run_uses_the_list_format(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 42")) as api:
        config = write_config(multi_task(api.url, 1, [COT, DIRECT]))
        result = run_cli(config, write_input([ROW]))
        assert api.call_count == 1
    row = result.rows[0]
    assert row["output"] == [{"solution": "#### 42", "icl_setup": "chain_of_thought"}]
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert isinstance(row["meta"], list)
    assert row["meta"][0]["evaluation_passed"] is True


# Spec: "`input` is the original row" — unchanged in the list format.
# Context: Output Changes; the spec's example row.
def test_input_is_still_echoed_unchanged(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 42")) as api:
        config = write_config(multi_task(api.url, 2))
        result = run_cli(config, write_input([ROW]))
    assert result.rows[0]["input"] == ROW


# Spec: "write only those two passing outputs" — a row that collects nothing
# writes an empty list (see AMBIGUITIES T45).
# Context: Examples (rejection partial result).
def test_row_with_no_solutions_writes_an_empty_list(write_config, write_input, run_cli):
    with FakeAPI(responder=always("", status=500)) as api:
        config = write_config(multi_task(api.url, 2))
        result = run_cli(config, write_input([ROW]))
    row = result.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}
    assert row["meta"] == []


# Spec: per-task summary fields gain "total_solutions" and
# "avg_solutions_per_input" beside "total" and "total_api_calls"
# Context: Output Changes (per-task summary fields).
def test_per_task_summary_reports_solution_counts(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5")) as api:
        document = {
            "defaults": base_defaults(api.url),
            "tasks": {
                "gsm8k": math_task(
                    generation={"scheme": "sample", "temperature": 0.8}, num_solutions=3
                )
            },
        }
        config = write_yaml(document)
        data = write_inputs({"gsm8k": [{"question": "q", "answer": "5"}] * 2})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    task = result.summary["tasks"]["gsm8k"]
    assert task["total"] == 2
    assert task["total_solutions"] == 6
    assert task["avg_solutions_per_input"] == 3.0
    assert task["total_api_calls"] == 6
    assert len(task_rows(result, "gsm8k")) == 2


# Spec: "`total_solutions`" counts only the solutions actually written.
# Context: Output Changes (per-task summary fields).
def test_total_solutions_counts_written_outputs(write_yaml, write_inputs, run_args, workdir):
    def responder(index, body):
        return Reply(content="#### 5" if index == 0 else "#### 9")

    with FakeAPI(responder=responder) as api:
        document = {
            "defaults": base_defaults(api.url),
            "tasks": {
                "gsm8k": math_task(
                    generation={"scheme": "rejection", "temperature": 0.8, "max_attempts": 4},
                    num_solutions=2,
                )
            },
        }
        config = write_yaml(document)
        data = write_inputs({"gsm8k": [{"question": "q", "answer": "5"}]})
        result = run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
    task = result.summary["tasks"]["gsm8k"]
    assert task["total_solutions"] == 1
    assert task["avg_solutions_per_input"] == 1.0
    assert task["total_api_calls"] == 4

"""The list output format used when ICL or several solutions are configured."""

from __future__ import annotations

from conftest import icl_setup, make_config

ROW = [{"question": "What is 15 + 27?", "answer": "42"}]
SETUPS = [icl_setup("chain_of_thought", "#### 4"), icl_setup("direct", "#### 4")]


def sample_config(server_url, num_solutions, **overrides):
    return make_config(
        server_url,
        generation={"scheme": "sample", "temperature": 0.7},
        num_solutions=num_solutions,
        **overrides,
    )


# Spec: "`output` becomes a list of objects, each containing the task's
# `output_field` plus `icl_setup`".
def test_output_is_a_list_of_solution_objects(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = sample_config(server.url, 2, icl={"setups": SETUPS[:1]})
    result = run_cli(config, ROW)
    assert result.exit_code == 0, result.stderr
    assert result.rows[0]["output"] == [
        {"solution": "#### 42", "icl_setup": "chain_of_thought"},
        {"solution": "#### 42", "icl_setup": "chain_of_thought"},
    ]


# Spec: "`icl_setup` is ... `null` when no ICL is configured".
def test_icl_setup_is_null_without_icl(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(sample_config(server.url, 2), ROW)
    assert result.rows[0]["output"] == [
        {"solution": "#### 42", "icl_setup": None},
        {"solution": "#### 42", "icl_setup": None},
    ]


# Spec: "when ICL is configured, use the list format even if `num_solutions ==
# 1`" -- "the single output item records the chosen `icl_setup`" and "`meta` is
# also a list and includes `evaluation_passed`".
def test_single_solution_icl_run_uses_the_list_format(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = make_config(server.url, num_solutions=1, icl={"setups": SETUPS})
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert row["output"] == [{"solution": "#### 42", "icl_setup": "chain_of_thought"}]
    assert isinstance(row["meta"], list)
    assert row["meta"][0]["evaluation_passed"] is True


# Spec: "when `num_solutions == 1` and no ICL is configured, keep the Part 1
# output format".
def test_part_1_format_without_icl_or_extra_solutions(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(make_config(server.url), ROW)
    row = result.rows[0]
    assert row["output"] == {"solution": "#### 42"}
    assert isinstance(row["meta"], dict)
    assert "icl_setup" not in row["meta"]


# Spec: the row keys are unchanged -- "input", "output", "result", "meta".
def test_list_format_keeps_the_row_keys(servers, run_cli):
    server = servers(contents=["#### 42"])
    result = run_cli(sample_config(server.url, 2), ROW)
    assert list(result.rows[0]) == ["input", "output", "result", "meta"]
    assert result.rows[0]["input"] == ROW[0]


# Spec: "`result.passed` is the count of passing solutions", "`result.failed`
# is the count of failed attempts", "`result.attempts` is the total number of
# generation attempts for the row" -- and nothing else. (T43)
def test_result_holds_exactly_the_three_counts(servers, run_cli):
    server = servers(contents=["#### 42", "#### 0"], workers=1)
    result = run_cli(sample_config(server.url, 2), ROW)
    assert result.rows[0]["result"] == {"passed": 1, "failed": 1, "attempts": 2}


# Spec: "`meta` is a list with one entry per attempt" and "each metadata entry
# includes `icl_setup` and `evaluation_passed`".
def test_meta_entries_carry_the_setup_and_verdict(servers, run_cli):
    server = servers(contents=["#### 42", "#### 0"], workers=1, prompt_tokens=80,
                     completion_tokens=15)
    config = sample_config(server.url, 2, icl={"setups": SETUPS, "strategy": "round_robin"})
    result = run_cli(config, ROW)
    metas = result.rows[0]["meta"]
    assert len(metas) == 2
    assert set(metas[0]) == {
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "icl_setup",
        "evaluation_passed",
    }
    assert [meta["icl_setup"] for meta in metas] == ["chain_of_thought", "direct"]
    assert [meta["evaluation_passed"] for meta in metas] == [True, False]
    assert metas[0]["prompt_tokens"] == 80


# Spec: "if evaluation is omitted in list format, `evaluation_passed` is
# `null` for each metadata entry, `result.passed` is the number of emitted
# outputs".
def test_without_evaluation_passed_counts_emitted_outputs(servers, run_cli):
    server = servers(contents=["#### 42"])
    config = sample_config(server.url, 3, evaluation=None)
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert row["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert [meta["evaluation_passed"] for meta in row["meta"]] == [None, None, None]


# Spec: "if evaluation is omitted ... `result.failed` is the number of attempts
# that produced no output".
def test_without_evaluation_failed_counts_empty_attempts(servers, run_cli):
    server = servers(contents=["#### 42"], fail_calls={1}, fail_status=400)
    config = sample_config(server.url, 3, evaluation=None)
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert len(row["output"]) == 2
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# Spec: the output list holds the solutions a row produced, so a row that
# produced none carries an empty list. (T50)
def test_row_with_no_usable_response_has_an_empty_output_list(servers, run_cli):
    server = servers(fail_calls=set(range(20)), fail_status=400)
    result = run_cli(sample_config(server.url, 2), ROW)
    row = result.rows[0]
    assert row["output"] == []
    assert row["meta"] == []
    assert row["result"] == {"passed": 0, "failed": 2, "attempts": 2}


# Spec: the documented list-format example row.
def test_documented_list_format_example(servers, run_cli):
    server = servers(contents=["15 + 27 = 42\n#### 42", "#### 42"], workers=1)
    config = sample_config(
        server.url, 2, icl={"setups": SETUPS, "strategy": "round_robin"}
    )
    result = run_cli(config, ROW)
    row = result.rows[0]
    assert row["output"] == [
        {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "chain_of_thought"},
        {"solution": "#### 42", "icl_setup": "direct"},
    ]
    assert row["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert row["meta"][0]["model"] == "gpt-4"

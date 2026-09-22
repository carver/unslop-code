"""Spec section: Part 3 / Output Changes (list-format rows)."""
from __future__ import annotations

from conftest import COT_SETUP, DIRECT_SETUP, base_config, icl_config
from mock_server import MockAPI, always, completion, sequence


ROW = {"question": "What is 15 + 27?", "answer": "42"}


# ---------------------------------------------------------------------------
# Phrase: "If ICL is configured or `num_solutions > 1`, the per-row output
#          format changes" + "when ICL is configured, use the list format even
#          if `num_solutions == 1`"
# Context: Part 3 / Output Changes, and the "Single-solution ICL run" example.
# ---------------------------------------------------------------------------
def test_icl_with_one_solution_still_uses_list_format(run_tool, write_config,
                                                      write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP], num_solutions=1))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert isinstance(row["output"], list)
    assert row["output"] == [{"solution": "#### 42",
                              "icl_setup": "chain_of_thought"}]
    assert isinstance(row["meta"], list) and len(row["meta"]) == 1
    assert row["meta"][0]["evaluation_passed"] is True
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}


# Context: same phrase - `num_solutions > 1` alone switches to list format.
def test_num_solutions_above_one_switches_format(run_tool, write_config,
                                                 write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=2,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert isinstance(row["output"], list) and len(row["output"]) == 2
    assert isinstance(row["meta"], list) and len(row["meta"]) == 2


# ---------------------------------------------------------------------------
# Phrase: "when `num_solutions == 1` and no ICL is configured, keep the Part 1
#          output format"
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_legacy_rows_keep_part1_format(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url, num_solutions=1))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"] == {"passed": True, "extracted_answer": "42",
                             "attempts": 1}
    assert isinstance(row["meta"], dict)
    assert "icl_setup" not in row["meta"]


# ---------------------------------------------------------------------------
# Phrase: "`output` becomes a list of objects, each containing the task's
#          `output_field` plus `icl_setup`"
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_output_items_carry_output_field_and_icl_setup(run_tool, write_config,
                                                       write_input):
    responder = sequence(["#### 42", "#### 42"])
    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP, DIRECT_SETUP], strategy="round_robin",
            num_solutions=2,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    outputs = res.rows[0]["output"]
    assert outputs == [
        {"solution": "#### 42", "icl_setup": "chain_of_thought"},
        {"solution": "#### 42", "icl_setup": "direct"},
    ]


# ---------------------------------------------------------------------------
# Phrase: "`icl_setup` is the chosen setup name, or `null` when no ICL is
#          configured"
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_icl_setup_is_null_without_icl(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(
            api.url, num_solutions=2,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert all(o["icl_setup"] is None for o in row["output"])
    assert all(m["icl_setup"] is None for m in row["meta"])


# ---------------------------------------------------------------------------
# Phrase: "`result.passed` is the count of passing solutions" /
#         "`result.failed` is the count of failed attempts" /
#         "`result.attempts` is the total number of generation attempts"
# Context: Part 3 / Output Changes (the example row: 2 passed, 5 failed,
# 7 attempts).
# ---------------------------------------------------------------------------
def test_result_counts(run_tool, write_config, write_input):
    def responder(req, i):
        return 200, completion("#### 42" if i in (1, 4) else "#### 0")

    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=2,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"] == {"passed": 2, "failed": 3, "attempts": 5}


# Context: same rules (AMBIGUITIES T45) - the list-format `result` object has
# exactly these three keys.
def test_result_key_set_in_list_format(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert set(res.rows[0]["result"]) == {"passed", "failed", "attempts"}


# ---------------------------------------------------------------------------
# Phrase: "`meta` is a list with one entry per attempt" / "each metadata entry
#          includes `icl_setup` and `evaluation_passed`"
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_meta_entries_per_attempt(run_tool, write_config, write_input):
    def responder(req, i):
        return 200, completion("#### 42" if i == 2 else "#### 0",
                               prompt_tokens=80, completion_tokens=15)

    with MockAPI(responder) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=1,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 6}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    metas = res.rows[0]["meta"]
    assert len(metas) == 3
    assert [m["evaluation_passed"] for m in metas] == [False, False, True]
    assert all(m["icl_setup"] == "chain_of_thought" for m in metas)
    assert set(metas[0]) == {
        "model", "prompt_tokens", "completion_tokens", "total_tokens",
        "latency_ms", "finish_reason", "icl_setup", "evaluation_passed"}
    assert metas[0]["model"] == "gpt-4"
    assert metas[0]["prompt_tokens"] == 80
    assert metas[0]["completion_tokens"] == 15
    assert metas[0]["total_tokens"] == 95
    assert metas[0]["finish_reason"] == "stop"
    assert isinstance(metas[0]["latency_ms"], int)


# ---------------------------------------------------------------------------
# Phrase: "if evaluation is omitted in list format, `evaluation_passed` is
#          `null` for each metadata entry, `result.passed` is the number of
#          emitted outputs, and `result.failed` is the number of attempts that
#          produced no output"
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_no_evaluation_in_list_format(run_tool, write_config, write_input):
    with MockAPI(always("some text")) as api:
        cfg = write_config(base_config(
            api.url, evaluation=None, num_solutions=3,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert all(m["evaluation_passed"] is None for m in row["meta"])


# Context: same phrase (AMBIGUITIES T48) - an attempt whose request keeps
# failing produces no output and counts as a failed attempt.
def test_failed_attempt_counts_as_failed_without_evaluation(run_tool,
                                                            write_config,
                                                            write_input):
    def responder(req, i):
        # The first logical attempt burns its 3 HTTP requests on 5xx.
        if i < 3:
            return 500, {"error": "boom"}
        return 200, completion("fine")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url, evaluation=None, num_solutions=2,
            generation={"scheme": "sample", "temperature": 0.7}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert [o["solution"] for o in row["output"]] == ["fine"]
    assert row["result"] == {"passed": 1, "failed": 1, "attempts": 2}


# ---------------------------------------------------------------------------
# Phrase: "write only those two passing outputs" (a row may collect fewer
#         solutions than requested) - AMBIGUITIES T54: a row that collects
#         none writes an empty list, not `null`.
# Context: Part 3 / Examples.
# ---------------------------------------------------------------------------
def test_row_with_no_passing_solutions_writes_empty_list(run_tool,
                                                         write_config,
                                                         write_input):
    with MockAPI(always("#### 0")) as api:
        cfg = write_config(icl_config(
            api.url, [COT_SETUP], num_solutions=2,
            generation={"scheme": "rejection", "temperature": 0.7,
                        "max_attempts": 3}))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# ---------------------------------------------------------------------------
# Phrase: the example row block ("input", "output", "result", "meta")
# Context: Part 3 / Output Changes - the row keys themselves are unchanged and
# `input` is the original row.
# ---------------------------------------------------------------------------
def test_row_keys_and_input_are_unchanged(run_tool, write_config,
                                          write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert set(row) == {"input", "output", "result", "meta"}
    assert row["input"] == ROW


# ---------------------------------------------------------------------------
# Phrase: "`output` becomes a list of objects, each containing the task's
#          `output_field`" - the configured `output_field` name is used.
# Context: Part 3 / Output Changes.
# ---------------------------------------------------------------------------
def test_output_field_name_is_respected(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP],
                                      output_field="answer_text"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert set(res.rows[0]["output"][0]) == {"answer_text", "icl_setup"}

"""Part 3 output rows: the list format for `output`, `result`, and `meta`."""
import threading

import pytest

from conftest import icl_block, make_config, marker_setups
from mock_api import MockAPI, always, chat_response

ROWS = [{"question": "q", "answer": "42"}]
SAMPLE = dict(scheme="sample", temperature=0.7)
REJECT = dict(scheme="rejection", temperature=0.7)
META_KEYS = {"model", "prompt_tokens", "completion_tokens", "total_tokens",
             "latency_ms", "finish_reason", "icl_setup", "evaluation_passed"}


def sequence_per_row(mapping, default=("#### 0",)):
    counts = {}
    lock = threading.Lock()

    def responder(payload, i):
        user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        with lock:
            k = counts.get(user, 0)
            counts[user] = k + 1
        seq = mapping.get(user, default)
        item = seq[k] if k < len(seq) else seq[-1]
        if isinstance(item, int):
            return item, {"error": "boom"}
        return 200, chat_response(item)
    return responder


# Spec: "If ICL is configured or `num_solutions > 1`, the per-row output
#        format changes" / "`output` becomes a list of objects, each
#        containing the task's `output_field` plus `icl_setup`"
# Context: Output Changes.
def test_output_items_carry_the_output_field_and_icl_setup(run_tool):
    icl = icl_block(marker_setups(["chain_of_thought"]))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 0, run.stderr
    output = run.rows[0]["output"]
    assert isinstance(output, list)
    assert output == [{"solution": "#### 42",
                       "icl_setup": "chain_of_thought"}]


def test_output_items_use_the_configured_output_field_name(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, output_field="answer_text",
                                   num_solutions=2, **SAMPLE), ROWS)
    assert run.returncode == 0, run.stderr
    assert all(set(o) == {"answer_text", "icl_setup"}
               for o in run.rows[0]["output"])


# Spec: "`icl_setup` is the chosen setup name, or `null` when no ICL is
#        configured"
# Context: Output Changes rules.
def test_icl_setup_is_null_without_icl(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert [o["icl_setup"] for o in row["output"]] == [None, None]
    assert [m["icl_setup"] for m in row["meta"]] == [None, None]


def test_icl_setup_records_the_setup_each_solution_used(run_tool):
    icl = icl_block(marker_setups(["A", "B", "C"]), strategy="round_robin")
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=3,
                                   **SAMPLE), ROWS)
    assert run.returncode == 0, run.stderr
    assert [o["icl_setup"] for o in run.rows[0]["output"]] == ["A", "B", "C"]


# Spec: "`result.passed` is the count of passing solutions" /
#       "`result.failed` is the count of failed attempts" /
#       "`result.attempts` is the total number of generation attempts for the
#        row"
# Context: Output Changes rules.
def test_result_counts_passing_solutions_failed_attempts_and_attempts(run_tool):
    seq = ["#### 42", "#### 0", "#### 42", "#### 0", "#### 0", "#### 0",
           "#### 0"]
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2,
                                   max_attempts=7, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# T50: `result` carries exactly these three keys in the list format.
def test_result_has_exactly_passed_failed_and_attempts(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert set(run.rows[0]["result"]) == {"passed", "failed", "attempts"}


def test_passed_plus_failed_equals_attempts(run_tool):
    seq = ["#### 42", "#### 0", "#### 42"]
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=3, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    result = run.rows[0]["result"]
    assert result["passed"] + result["failed"] == result["attempts"] == 3
    assert result["passed"] == 2


# Spec: "`meta` is a list with one entry per attempt" / "each metadata entry
#        includes `icl_setup` and `evaluation_passed`"
# Context: Output Changes rules.
def test_meta_is_a_list_with_one_entry_per_attempt(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2,
                                   max_attempts=5, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert isinstance(row["meta"], list)
    assert len(row["meta"]) == row["result"]["attempts"] == 5


def test_meta_entries_keep_the_part_1_fields_plus_the_new_ones(run_tool):
    icl = icl_block(marker_setups(["A"]))
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert isinstance(meta, list) and len(meta) == 1
    assert set(meta[0]) == META_KEYS
    assert meta[0]["model"] == "gpt-4"
    assert meta[0]["prompt_tokens"] == 45
    assert meta[0]["completion_tokens"] == 120
    assert meta[0]["total_tokens"] == 165
    assert meta[0]["finish_reason"] == "stop"
    assert isinstance(meta[0]["latency_ms"], int)
    assert meta[0]["icl_setup"] == "A"
    assert meta[0]["evaluation_passed"] is True


def test_evaluation_passed_tracks_each_attempt(run_tool):
    seq = ["#### 0", "#### 0", "#### 42"]
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=1,
                                   max_attempts=5, icl=icl_block(
                                       marker_setups(["A"])), **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    assert [m["evaluation_passed"] for m in run.rows[0]["meta"]] == [
        False, False, True]


# Spec: "if evaluation is omitted in list format, `evaluation_passed` is
#        `null` for each metadata entry, `result.passed` is the number of
#        emitted outputs, and `result.failed` is the number of attempts that
#        produced no output"
# Context: Output Changes rules.
def test_without_evaluation_passed_counts_emitted_outputs(run_tool):
    with MockAPI(always("anything")) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None,
                                   num_solutions=3, **SAMPLE), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert len(row["output"]) == 3
    assert row["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert [m["evaluation_passed"] for m in row["meta"]] == [None, None, None]


def test_without_evaluation_failed_counts_attempts_with_no_output(run_tool):
    # attempt 2's three HTTP calls all fail, so it emits nothing.
    seq = ["ok1", 500, 500, 500, "ok3"]
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None,
                                   num_solutions=3, **SAMPLE), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert [o["solution"] for o in row["output"]] == ["ok1", "ok3"]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}


# Spec: "when `num_solutions == 1` and no ICL is configured, keep the Part 1
#        output format"
# Context: Output Changes rules.
@pytest.mark.parametrize("args", [(), ("--num-solutions", "1")])
def test_part_1_format_when_single_solution_and_no_icl(run_tool, args):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS, args=args)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == {"solution": "#### 42"}
    assert isinstance(row["meta"], dict)
    assert set(row["meta"]) == {"model", "prompt_tokens", "completion_tokens",
                                "total_tokens", "latency_ms", "finish_reason"}
    assert row["result"] == {"passed": True, "extracted_answer": "42",
                             "attempts": 1}


# Spec: "when ICL is configured, use the list format even if
#        `num_solutions == 1`"
# Spec (Examples): "with `num_solutions: 1` and ICL enabled, `output` is still
#   a list / the single output item records the chosen `icl_setup` / `meta` is
#   also a list and includes `evaluation_passed`"
# Context: Output Changes rules / Examples.
def test_single_solution_icl_run_still_uses_the_list_format(run_tool):
    icl = icl_block(marker_setups(["direct"]), strategy="fixed")
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=1),
                       ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == [{"solution": "#### 42", "icl_setup": "direct"}]
    assert isinstance(row["meta"], list) and len(row["meta"]) == 1
    assert row["meta"][0]["evaluation_passed"] is True
    assert row["result"] == {"passed": 1, "failed": 0, "attempts": 1}


# Spec: the `input` field is unchanged -- the whole input row.
def test_input_is_still_the_whole_row(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2, **SAMPLE),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["input"] == {"question": "q", "answer": "42"}


def test_one_output_row_per_input_row_in_input_order(run_tool):
    rows = [{"question": "a", "answer": "42"}, {"question": "b", "answer": "42"},
            {"question": "c", "answer": "42"}]
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2, **SAMPLE),
                       rows)
    assert run.returncode == 0, run.stderr
    assert [r["input"]["question"] for r in run.rows] == ["a", "b", "c"]
    assert all(len(r["output"]) == 2 for r in run.rows)


# T49: a row that collects nothing writes an empty list, not null.
def test_row_with_no_collected_solutions_writes_an_empty_list(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2,
                                   max_attempts=3, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["output"] == []
    assert row["result"] == {"passed": 0, "failed": 3, "attempts": 3}


# T51: an attempt whose HTTP calls are exhausted still counts as an attempt.
def test_failed_attempt_counts_in_attempts_and_failed(run_tool):
    seq = [500, 500, 500, "#### 42", "#### 42"]
    with MockAPI(sequence_per_row({"q": seq})) as api:
        run = run_tool(make_config(api_url=api.url, num_solutions=2,
                                   max_attempts=4, **REJECT), ROWS)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert len(row["output"]) == 2
    assert len(row["meta"]) == 2      # no metadata for the response-less attempt


# The spec's worked output row: shape of every field together.
# Context: Output Changes.
def test_spec_output_example_shape(run_tool):
    icl = icl_block(marker_setups(["chain_of_thought", "direct"]),
                    strategy="round_robin")
    rows = [{"question": "What is 15 + 27?", "answer": "42"}]
    seq = ["#### 0", "15 + 27 = 42\n#### 42", "#### 0", "#### 42", "#### 0",
           "#### 0", "#### 0"]
    with MockAPI(sequence_per_row({"What is 15 + 27?": seq})) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, num_solutions=2,
                                   max_attempts=7, **REJECT), rows)
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["input"] == {"question": "What is 15 + 27?", "answer": "42"}
    assert row["output"] == [
        {"solution": "15 + 27 = 42\n#### 42", "icl_setup": "direct"},
        {"solution": "#### 42", "icl_setup": "direct"}]
    assert row["result"] == {"passed": 2, "failed": 2, "attempts": 4}
    assert set(row["meta"][0]) == META_KEYS

"""Per-row output shape: input, output, result, meta."""
import json

import pytest

from conftest import make_config
from mock_api import MockAPI, always, per_question, chat_response


# Spec: "Write one JSON object per input row, in the same order as the input."
# Context: Output.
def test_one_output_row_per_input_row_in_order(run_tool):
    rows = [{"question": "q%d" % i, "answer": "5"} for i in range(6)]
    with MockAPI(per_question({"q%d" % i: "#### %d" % i for i in range(6)},
                              default="#### x")) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    out = run.rows
    assert len(out) == 6
    assert [r["input"]["question"] for r in out] == ["q%d" % i for i in range(6)]


def test_output_is_jsonl_one_object_per_line(run_tool, workdir):
    rows = [{"question": "a", "answer": "5"}, {"question": "b", "answer": "5"}]
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url), rows)
    assert run.returncode == 0, run.stderr
    lines = [l for l in open(run.output_path).read().splitlines() if l.strip()]
    assert len(lines) == 2
    for line in lines:
        assert isinstance(json.loads(line), dict)


# Spec: "input is the original row, unchanged"
def test_input_echoed_unchanged(run_tool):
    row = {"question": "Sarah has 5 apples and buys 3 more. How many does she have?",
           "answer": "8", "extra": {"nested": [1, 2, 3]}, "id": 17}
    with MockAPI(always("#### 8")) as api:
        run = run_tool(make_config(api_url=api.url), [row])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["input"] == row


# Spec: "output is an object with one key named by output_field"
def test_output_key_is_named_by_output_field(run_tool):
    text = "Let me solve this step by step.\n5 + 3 = 8\n#### 8"
    with MockAPI(always(text)) as api:
        run = run_tool(make_config(api_url=api.url, output_field="solution"),
                       [{"question": "q", "answer": "8"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["output"] == {"solution": text}


def test_output_key_follows_a_different_output_field(run_tool):
    with MockAPI(always("hello")) as api:
        run = run_tool(make_config(api_url=api.url, output_field="completion",
                                   evaluation=None),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert list(run.rows[0]["output"].keys()) == ["completion"]


# Spec: "result.attempts is the number of logical generation attempts for that
#        row: 1 for greedy and sample"
@pytest.mark.parametrize("scheme,temperature", [("greedy", None), ("sample", 0.7)])
def test_attempts_is_one_for_greedy_and_sample(run_tool, scheme, temperature):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, scheme=scheme,
                                   temperature=temperature),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == 1


# Spec: "result.passed is true for a passing evaluation, false for a failing
#        evaluation, and null when no evaluation is configured"
def test_result_block_keys(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert set(run.rows[0]["result"]) == {"passed", "extracted_answer", "attempts"}


# Spec: meta object shape
#   {"model", "prompt_tokens", "completion_tokens", "total_tokens",
#    "latency_ms", "finish_reason"}
# Context: Output.
def test_meta_object_fields(run_tool):
    responder = lambda p, i: (200, chat_response("#### 5", prompt_tokens=45,
                                                 completion_tokens=120,
                                                 finish_reason="stop"))
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, model="gpt-4"),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    meta = run.rows[0]["meta"]
    assert isinstance(meta, dict)
    assert meta["model"] == "gpt-4"
    assert meta["prompt_tokens"] == 45
    assert meta["completion_tokens"] == 120
    assert meta["total_tokens"] == 165
    assert meta["finish_reason"] == "stop"
    assert set(meta) == {"model", "prompt_tokens", "completion_tokens",
                         "total_tokens", "latency_ms", "finish_reason"}


# Spec: "meta.latency_ms is wall-clock latency for that API call"
def test_latency_ms_reflects_wall_clock_of_the_call(run_tool):
    with MockAPI(always("#### 5"), service_seconds=0.25) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    latency = run.rows[0]["meta"]["latency_ms"]
    assert isinstance(latency, (int, float))
    assert 200 <= latency < 5000


# Spec: finish_reason is carried through from the response
def test_finish_reason_length_is_carried_through(run_tool):
    responder = lambda p, i: (200, chat_response("truncated...",
                                                 finish_reason="length"))
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, evaluation=None),
                       [{"question": "q"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["meta"]["finish_reason"] == "length"


# Spec (Examples): the greedy example's exact output row
def test_greedy_example_from_spec(run_tool):
    config = {
        "task": {
            "name": "math_solve",
            "api_url": None,  # replaced below
            "model": "gpt-4",
            "rpm": 60,
            "prompt": {"system": "Solve the math problem. Final answer after ####.",
                       "user": "{question}"},
            "generation": {"scheme": "greedy", "max_tokens": 256},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution",
        }
    }
    responder = lambda p, i: (200, chat_response("2 + 3 = 5\n#### 5",
                                                 prompt_tokens=30,
                                                 completion_tokens=10))
    with MockAPI(responder) as api:
        config["task"]["api_url"] = api.url
        run = run_tool(config, [{"question": "What is 2 + 3?", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5",
                             "attempts": 1}
    assert row["meta"]["model"] == "gpt-4"
    assert row["meta"]["prompt_tokens"] == 30
    assert row["meta"]["completion_tokens"] == 10
    assert row["meta"]["total_tokens"] == 40
    assert row["meta"]["finish_reason"] == "stop"


def test_top_level_row_keys(run_tool):
    with MockAPI(always("#### 5")) as api:
        run = run_tool(make_config(api_url=api.url),
                       [{"question": "q", "answer": "5"}])
    assert run.returncode == 0, run.stderr
    assert set(run.rows[0]) == {"input", "output", "result", "meta"}

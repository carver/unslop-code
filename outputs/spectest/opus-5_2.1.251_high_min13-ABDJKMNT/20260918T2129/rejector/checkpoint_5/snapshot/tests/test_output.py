"""Per-row output shape: input/output/result/meta."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, always, completion, cycle
from conftest import base_config


# Spec: the greedy example output row, end to end
def test_greedy_example_row_matches_the_spec_shape(write_config, write_input, run_cli):
    config_map = {
        "task": {
            "name": "math_solve",
            "api_url": "",
            "model": "gpt-4",
            "rpm": 60,
            "prompt": {"system": "Solve the math problem. Final answer after ####.", "user": "{question}"},
            "generation": {"scheme": "greedy", "max_tokens": 256},
            "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "last_number"},
            "output_field": "solution",
        }
    }
    with FakeAPIServer(always("2 + 3 = 5\n#### 5", prompt_tokens=30, completion_tokens=10)) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "What is 2 + 3?", "answer": "5"}]))

    row = result.rows[0]
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert set(row) == {"input", "output", "result", "meta"}


# Spec: "output is an object with one key named by output_field"
def test_output_key_is_named_by_output_field(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["output_field"] = "completion_text"
    with FakeAPIServer(always("#### 5")) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
    assert result.rows[0]["output"] == {"completion_text": "#### 5"}


# Spec: "result.attempts is ... 1 for greedy and sample"
def test_attempts_is_one_for_greedy(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 9")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
    assert result.rows[0]["result"]["attempts"] == 1


# Spec: "meta is a single metadata object for one-attempt rows" with the
# documented keys
def test_meta_object_for_single_attempt_rows(write_config, write_input, run_cli):
    with FakeAPIServer(
        always("#### 5", model="gpt-4", prompt_tokens=45, completion_tokens=120, finish_reason="stop")
    ) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    meta = result.rows[0]["meta"]
    assert isinstance(meta, dict)
    assert meta["model"] == "gpt-4"
    assert meta["prompt_tokens"] == 45
    assert meta["completion_tokens"] == 120
    assert meta["total_tokens"] == 165
    assert meta["finish_reason"] == "stop"
    assert set(meta) == {
        "model", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason",
    }


# Spec: "meta.latency_ms is wall-clock latency for that API call"
def test_latency_ms_reflects_the_call_duration(write_config, write_input, run_cli):
    def slow(payload, index):
        return Reply(completion("#### 5"), delay=0.25)

    with FakeAPIServer(slow) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    latency = result.rows[0]["meta"]["latency_ms"]
    assert isinstance(latency, (int, float))
    assert 200 <= latency < 5000


# Spec: "finish_reason" is carried through from the response
def test_finish_reason_is_carried_through(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5", finish_reason="length")) as api:
        config = write_config(base_config(api.url))
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))
    assert result.rows[0]["meta"]["finish_reason"] == "length"


# Spec: "for rejection sampling with multiple attempts it [meta] is a list
# with one metadata object per attempt"
def test_meta_is_a_list_for_multi_attempt_rejection(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {"scheme": "rejection", "temperature": 0.8, "n": 3, "max_tokens": 64}
    with FakeAPIServer(cycle(["#### 1", "#### 2", "#### 5"])) as api:
        config_map["task"]["api_url"] = api.url
        config = write_config(config_map)
        result = run_cli(config, write_input([{"question": "q", "answer": "5"}]))

    meta = result.rows[0]["meta"]
    assert isinstance(meta, list)
    assert len(meta) == 3
    assert all(set(entry) >= {"model", "total_tokens", "latency_ms"} for entry in meta)


# Spec: output lines are newline-delimited JSON objects
def test_output_file_is_newline_delimited_json(write_config, write_input, run_cli):
    with FakeAPIServer(always("#### 5")) as api:
        config = write_config(base_config(api.url))
        rows = write_input([{"question": f"q{i}", "answer": "5"} for i in range(3)])
        result = run_cli(config, rows)
    text = result.output_path.read_text()
    assert text.endswith("\n")
    assert len(text.strip().split("\n")) == 3

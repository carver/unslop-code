"""Spec section: Output (per-row shape and rules)."""
from __future__ import annotations

import json

from conftest import base_config
from mock_server import MockAPI, always, completion, sequence


# ---------------------------------------------------------------------------
# Phrase: "Write one JSON object per input row, in the same order as the input."
# Context: Output.
# ---------------------------------------------------------------------------
def test_one_row_per_input_in_order(run_tool, write_config, write_input):
    def responder(req, i):
        # Slower replies for earlier rows, so completion order != input order.
        user = req["messages"][-1]["content"]
        import time
        time.sleep(0.25 if user == "q0" else 0.0)
        return 200, completion(f"#### {user[1:]}")

    with MockAPI(responder) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": f"q{i}", "answer": str(i)}
                            for i in range(5)])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    rows = res.rows
    assert [r["input"]["question"] for r in rows] == [f"q{i}" for i in range(5)]
    for i, r in enumerate(rows):
        assert r["output"] == {"solution": f"#### {i}"}


# Context: same phrase - output is JSONL: one JSON object per line.
def test_output_is_jsonl(run_tool, write_config, write_input, workdir):
    out = workdir / "results.jsonl"
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "a", "answer": "5"},
                            {"question": "b", "answer": "5"}])
        res = run_tool(cfg, data, output=str(out))
    assert res.returncode == 0, res
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert isinstance(json.loads(line), dict)


# ---------------------------------------------------------------------------
# Phrase: the "Per-row shape" JSON block - top-level keys input/output/result/meta
# Context: Output.
# ---------------------------------------------------------------------------
def test_per_row_shape(run_tool, write_config, write_input):
    body = completion("Let me solve this step by step.\n5 + 3 = 8\n#### 8",
                      prompt_tokens=45, completion_tokens=120)
    with MockAPI(lambda req, i: (200, body)) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "Sarah has 5 apples and buys 3 more.",
                             "answer": "8"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert set(row) == {"input", "output", "result", "meta"}
    assert row["result"] == {"passed": True, "extracted_answer": "8",
                             "attempts": 1}
    assert set(row["meta"]) == {"model", "prompt_tokens", "completion_tokens",
                                "total_tokens", "latency_ms", "finish_reason"}


# ---------------------------------------------------------------------------
# Phrase: "input is the original row, unchanged"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_input_row_is_unchanged(run_tool, write_config, write_input):
    original = {"question": "q", "answer": "5", "id": 7,
                "extra": {"nested": [1, 2, 3]}, "unused": None}
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([original])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["input"] == original


# ---------------------------------------------------------------------------
# Phrase: "output is an object with one key named by output_field"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_output_field_names_the_key(run_tool, write_config, write_input):
    with MockAPI(always("the text")) as api:
        cfg = write_config(base_config(api.url, output_field="completion",
                                       evaluation=None))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] == {"completion": "the text"}


# ---------------------------------------------------------------------------
# Phrase: "if all attempts fail, output is null"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_output_null_when_all_attempts_fail(run_tool, write_config,
                                            write_input):
    with MockAPI(always("#### 1")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 3}))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] is None


# Context: same phrase, contrast - a greedy row that merely fails evaluation
# keeps its output.
def test_failing_greedy_row_keeps_output(run_tool, write_config, write_input):
    with MockAPI(always("#### 1")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"] == {"solution": "#### 1"}
    assert res.rows[0]["result"]["passed"] is False


# ---------------------------------------------------------------------------
# Phrase: "result.passed is true for a passing evaluation, false for a failing
#          evaluation, and null when no evaluation is configured"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_passed_tri_state(run_tool, write_config, write_input, workdir):
    with MockAPI(always("#### 5")) as api:
        cfg_pass = write_config(base_config(api.url), name="pass.yaml")
        cfg_none = write_config(base_config(api.url, evaluation=None),
                                name="none.yaml")
        data_pass = write_input([{"question": "q", "answer": "5"}], "p.jsonl")
        data_fail = write_input([{"question": "q", "answer": "6"}], "f.jsonl")
        data_none = write_input([{"question": "q"}], "n.jsonl")
        r_pass = run_tool(cfg_pass, data_pass,
                          output=str(workdir / "o_pass.jsonl"))
        r_fail = run_tool(cfg_pass, data_fail,
                          output=str(workdir / "o_fail.jsonl"))
        r_none = run_tool(cfg_none, data_none,
                          output=str(workdir / "o_none.jsonl"))
    assert r_pass.rows[0]["result"]["passed"] is True
    assert r_fail.rows[0]["result"]["passed"] is False
    assert r_none.rows[0]["result"]["passed"] is None


# ---------------------------------------------------------------------------
# Phrase: "result.extracted_answer is the extracted comparison value, or null
#          when there is no evaluation or no output"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_extracted_answer_null_without_evaluation(run_tool, write_config,
                                                  write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": "q"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] is None


def test_extracted_answer_null_without_output(run_tool, write_config,
                                              write_input):
    with MockAPI(always("#### 1")) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 2}))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["extracted_answer"] is None


# ---------------------------------------------------------------------------
# Phrase: "result.attempts is the number of logical generation attempts for
#          that row: 1 for greedy and sample, 1..n for rejection"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_attempts_is_one_for_greedy_and_sample(run_tool, write_config,
                                               write_input, workdir):
    with MockAPI(always("#### 5")) as api:
        greedy = write_config(base_config(api.url), name="g.yaml")
        sample = write_config(base_config(
            api.url, generation={"scheme": "sample", "temperature": 0.5}),
            name="s.yaml")
        data = write_input([{"question": "q", "answer": "5"}])
        rg = run_tool(greedy, data, output=str(workdir / "o_g.jsonl"))
        rs = run_tool(sample, data, output=str(workdir / "o_s.jsonl"))
    assert rg.rows[0]["result"]["attempts"] == 1
    assert rs.rows[0]["result"]["attempts"] == 1


def test_attempts_counts_rejection_attempts(run_tool, write_config,
                                            write_input):
    responder = sequence(["#### 1", "#### 2", "#### 3", "#### 42"])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 6}))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["result"]["attempts"] == 4


# ---------------------------------------------------------------------------
# Phrase: "meta is a single metadata object for one-attempt rows; for rejection
#          sampling with multiple attempts it is a list with one metadata object
#          per attempt"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_meta_object_for_one_attempt_row(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert isinstance(res.rows[0]["meta"], dict)


def test_meta_list_matches_attempts(run_tool, write_config, write_input):
    responder = sequence([
        (200, completion("#### 1", prompt_tokens=10, completion_tokens=1)),
        (200, completion("#### 2", prompt_tokens=10, completion_tokens=2)),
        (200, completion("#### 42", prompt_tokens=10, completion_tokens=3)),
    ])
    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.8, "n": 5}))
        data = write_input([{"question": "q", "answer": "42"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    metas = res.rows[0]["meta"]
    assert isinstance(metas, list) and len(metas) == 3
    assert [m["completion_tokens"] for m in metas] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Phrase: "meta.latency_ms is wall-clock latency for that API call"
# Context: Output rules.
# ---------------------------------------------------------------------------
def test_latency_ms_reflects_call_duration(run_tool, write_config, write_input):
    with MockAPI(always("#### 5"), delay=0.3) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    latency = res.rows[0]["meta"]["latency_ms"]
    assert isinstance(latency, int)
    assert 250 <= latency < 5000


# ---------------------------------------------------------------------------
# Phrase: the "meta.model" field of the per-row shape ("model": "gpt-4")
# Context: Output.  It is the configured model.
# ---------------------------------------------------------------------------
def test_meta_model_is_configured_model(run_tool, write_config, write_input):
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url, model="my-model"))
        data = write_input([{"question": "q", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.rows[0]["meta"]["model"] == "my-model"


# Context: Output / rows preserve non-ASCII content faithfully.
def test_unicode_roundtrip(run_tool, write_config, write_input, workdir):
    out = workdir / "results.jsonl"
    with MockAPI(always("la réponse est 5 — voilà")) as api:
        cfg = write_config(base_config(api.url, evaluation=None))
        data = write_input([{"question": "Combien font 2 + 3 ?"}])
        res = run_tool(cfg, data, output=str(out))
    assert res.returncode == 0, res
    row = json.loads(out.read_text().splitlines()[0])
    assert row["output"]["solution"] == "la réponse est 5 — voilà"
    assert row["input"]["question"] == "Combien font 2 + 3 ?"

"""Spec section: Input (JSONL parsing) and Examples (end-to-end)."""
from __future__ import annotations

import json

from conftest import base_config
from mock_server import MockAPI, always, completion, per_prompt


# ---------------------------------------------------------------------------
# Phrase: "The input file is JSONL with one object per line."
# Context: Input.  The spec's two-row example file.
# ---------------------------------------------------------------------------
def test_jsonl_example_rows(run_tool, write_config, write_input, workdir):
    path = workdir / "data.jsonl"
    path.write_text(
        '{"question": "Sarah has 5 apples and buys 3 more. How many does she have?", "answer": "8"}\n'
        '{"question": "A train travels 60 miles in 2 hours. What is its speed in mph?", "answer": "30"}\n'
    )
    replies = {
        "Sarah has 5 apples and buys 3 more. How many does she have?":
            "5 + 3 = 8\n#### 8",
        "A train travels 60 miles in 2 hours. What is its speed in mph?":
            "60 / 2 = 30\n#### 30",
    }
    with MockAPI(per_prompt(replies)) as api:
        cfg = write_config(base_config(api.url))
        res = run_tool(cfg, str(path))
    assert res.returncode == 0, res
    rows = res.rows
    assert len(rows) == 2
    assert all(r["result"]["passed"] for r in rows)
    assert res.summary["passed"] == 2


# Context: same phrase - blank lines between records are tolerated and do not
# become rows.
def test_blank_lines_are_skipped(run_tool, write_config, write_input, workdir):
    path = workdir / "data.jsonl"
    path.write_text('{"question": "a", "answer": "5"}\n\n'
                    '{"question": "b", "answer": "5"}\n\n')
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        res = run_tool(cfg, str(path))
    assert res.returncode == 0, res
    assert res.summary["total"] == 2
    assert len(res.rows) == 2


# Context: same phrase - a final line without a trailing newline still counts.
def test_no_trailing_newline(run_tool, write_config, workdir):
    path = workdir / "data.jsonl"
    path.write_text('{"question": "a", "answer": "5"}')
    with MockAPI(always("#### 5")) as api:
        cfg = write_config(base_config(api.url))
        res = run_tool(cfg, str(path))
    assert res.returncode == 0, res
    assert res.summary["total"] == 1


# Context: Input - a JSONL line that is not an object is an input error.
def test_non_object_line_exits_1(run_tool, write_config, workdir):
    path = workdir / "data.jsonl"
    path.write_text('[1, 2, 3]\n')
    cfg = write_config(base_config("http://127.0.0.1:1"))
    res = run_tool(cfg, str(path))
    assert res.returncode == 1
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Phrase: the "Greedy example" - config, input, run, and the exact output row.
# Context: Examples.
# ---------------------------------------------------------------------------
def test_greedy_example_end_to_end(run_tool, write_config, write_input):
    body = completion("2 + 3 = 5\n#### 5", prompt_tokens=30,
                      completion_tokens=10)
    with MockAPI(lambda req, i: (200, body)) as api:
        cfg = write_config({
            "task": {
                "name": "math_solve",
                "api_url": api.url,
                "model": "gpt-4",
                "rpm": 60,
                "prompt": {
                    "system": "Solve the math problem. Final answer after ####.",
                    "user": "{question}",
                },
                "generation": {"scheme": "greedy", "max_tokens": 256},
                "evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": "last_number"},
                "output_field": "solution",
            }
        })
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["input"] == {"question": "What is 2 + 3?", "answer": "5"}
    assert row["output"] == {"solution": "2 + 3 = 5\n#### 5"}
    assert row["result"] == {"passed": True, "extracted_answer": "5",
                             "attempts": 1}
    meta = row["meta"]
    assert meta["model"] == "gpt-4"
    assert meta["prompt_tokens"] == 30
    assert meta["completion_tokens"] == 10
    assert meta["total_tokens"] == 40
    assert meta["finish_reason"] == "stop"
    assert isinstance(meta["latency_ms"], int)


# ---------------------------------------------------------------------------
# Phrase: "Rejection example with n: 3: if the first two responses fail
#          evaluation and the third passes, the output row records attempts: 3,
#          keeps the third response as output, and includes three metadata
#          entries."
# Context: Examples.
# ---------------------------------------------------------------------------
def test_rejection_example_end_to_end(run_tool, write_config, write_input):
    replies = ["nope 1", "nope 2", "the answer\n#### 5"]

    def responder(req, i):
        return 200, completion(replies[min(i, 2)])

    with MockAPI(responder) as api:
        cfg = write_config(base_config(
            api.url,
            generation={"scheme": "rejection", "temperature": 0.7, "n": 3}))
        data = write_input([{"question": "What is 2 + 3?", "answer": "5"}])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    row = res.rows[0]
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"solution": "the answer\n#### 5"}
    assert len(row["meta"]) == 3

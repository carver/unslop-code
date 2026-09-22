"""Rejection sampling: attempts, first-passing response, exhaustion."""
import threading

import pytest

from conftest import make_config
from mock_api import MockAPI, always, chat_response


def per_row_sequence(mapping, default=("#### 0",)):
    """Respond with mapping[user_content][k] for the k-th call of that row."""
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


REJ = dict(scheme="rejection", temperature=0.7)


# Spec: "rejection: ... make up to n attempts and keep the first passing
#        response"
# Context: Generation behavior.
def test_rejection_stops_at_first_passing_attempt(run_tool):
    # Two failures then a pass, with n=5: exactly 3 calls are made.
    responder = per_row_sequence({"q": ["#### 1", "#### 2", "#### 42", "#### 9"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, n=5, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 3
    assert row["result"]["attempts"] == 3
    assert row["result"]["passed"] is True
    assert row["output"] == {"solution": "#### 42"}
    assert row["result"]["extracted_answer"] == "42"


# Spec (Examples): "Rejection example with n: 3: if the first two responses
#   fail evaluation and the third passes, the output row records attempts: 3,
#   keeps the third response as output, and includes three metadata entries."
def test_rejection_example_n3_third_attempt_passes(run_tool):
    responder = per_row_sequence({"q": ["#### 1", "#### 2", "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, n=3, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["result"]["attempts"] == 3
    assert row["output"] == {"solution": "#### 42"}
    assert isinstance(row["meta"], list)
    assert len(row["meta"]) == 3


# Spec: "meta ... for rejection sampling with multiple attempts it is a list
#        with one metadata object per attempt"
def test_rejection_meta_list_entries_have_full_meta_shape(run_tool):
    responder = per_row_sequence({"q": ["#### 1", "#### 42"]})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, n=3, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    metas = run.rows[0]["meta"]
    assert isinstance(metas, list) and len(metas) == 2
    for meta in metas:
        assert set(meta) == {"model", "prompt_tokens", "completion_tokens",
                             "total_tokens", "latency_ms", "finish_reason"}


# T1: a rejection row that passes on its first attempt is a one-attempt row,
# so its meta is a single object rather than a one-element list.
def test_rejection_first_attempt_pass_uses_single_meta_object(run_tool):
    with MockAPI(always("#### 42")) as api:
        run = run_tool(make_config(api_url=api.url, n=3, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert row["result"]["attempts"] == 1
    assert isinstance(row["meta"], dict)
    assert api.call_count == 1


# Spec: "if all attempts fail, output null with "passed": false"
# Context: Generation behavior / the exhaustion example in Output.
def test_rejection_exhaustion_shape(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, n=5, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    row = run.rows[0]
    assert api.call_count == 5
    assert row["output"] is None
    assert row["result"]["passed"] is False
    assert row["result"]["extracted_answer"] is None
    assert row["result"]["attempts"] == 5
    assert isinstance(row["meta"], list)
    assert len(row["meta"]) == 5


# Spec: "result.attempts is ... 1..n for rejection"
@pytest.mark.parametrize("passing_index", [0, 1, 2, 3])
def test_attempts_counts_logical_generations(run_tool, passing_index):
    seq = ["#### 0"] * passing_index + ["#### 42"]
    responder = per_row_sequence({"q": seq})
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, n=4, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["attempts"] == passing_index + 1


def test_rejection_never_exceeds_n_attempts(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, n=2, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert api.call_count == 2
    assert run.rows[0]["result"]["attempts"] == 2


def test_rejection_sends_configured_temperature_on_every_attempt(run_tool):
    with MockAPI(always("#### 0")) as api:
        run = run_tool(make_config(api_url=api.url, n=3, **REJ),
                       [{"question": "q", "answer": "42"}])
    assert run.returncode == 0, run.stderr
    assert [c["temperature"] for c in api.calls] == [0.7, 0.7, 0.7]


def test_rejection_across_multiple_rows_is_independent(run_tool):
    responder = per_row_sequence({
        "a": ["#### 42"],                      # passes immediately
        "b": ["#### 1", "#### 2", "#### 42"],  # passes on the third
        "c": ["#### 9"],                       # never passes
    })
    rows = [{"question": "a", "answer": "42"},
            {"question": "b", "answer": "42"},
            {"question": "c", "answer": "42"}]
    with MockAPI(responder) as api:
        run = run_tool(make_config(api_url=api.url, n=3, **REJ), rows)
    assert run.returncode == 0, run.stderr
    out = run.rows
    assert [r["result"]["attempts"] for r in out] == [1, 3, 3]
    assert [r["result"]["passed"] for r in out] == [True, True, False]
    assert out[2]["output"] is None
    assert api.call_count == 1 + 3 + 3

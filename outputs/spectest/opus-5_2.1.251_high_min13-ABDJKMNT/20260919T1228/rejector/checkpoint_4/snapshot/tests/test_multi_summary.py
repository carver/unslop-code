"""The `tasks` object in the summary, and cross-task scheduling."""

from __future__ import annotations

from conftest import exact_match_task, make_multi_config

PASSING = [{"question": "q", "answer": "42"}]
FAILING = [{"question": "q", "answer": "7"}]


def two_task_config(server_url, **defaults) -> dict:
    return make_multi_config(
        server_url,
        {"gsm8k": exact_match_task(), "mmlu": exact_match_task(output_field="choice")},
        **defaults,
    )


# Spec: "The stdout summary now includes a `tasks` object keyed by executed
# task name" with total, passed, failed and total_api_calls per task.
def test_tasks_object_is_keyed_by_task_name(server, run_multi):
    result = run_multi(two_task_config(server.url), {"gsm8k": PASSING, "mmlu": FAILING})
    assert result.exit_code == 0, result.stderr
    assert set(result.summary["tasks"]) == {"gsm8k", "mmlu"}


# Spec: the per-task object carries exactly the documented keys, including the
# solution counts Part 3 adds. (T21, T48)
def test_per_task_keys(server, run_multi):
    result = run_multi(two_task_config(server.url), {"gsm8k": PASSING, "mmlu": FAILING})
    assert set(result.summary["tasks"]["gsm8k"]) == {
        "total",
        "passed",
        "failed",
        "total_api_calls",
        "total_solutions",
        "avg_solutions_per_input",
    }


# Spec: per-task counts follow the Part 1 rules for passed and failed rows.
def test_per_task_counts(server, run_multi):
    result = run_multi(
        two_task_config(server.url),
        {"gsm8k": PASSING * 3, "mmlu": FAILING * 2},
    )
    assert result.summary["tasks"]["gsm8k"] == {
        "total": 3,
        "passed": 3,
        "failed": 0,
        "total_api_calls": 3,
        "total_solutions": 3,
        "avg_solutions_per_input": 1.0,
    }
    assert result.summary["tasks"]["mmlu"] == {
        "total": 2,
        "passed": 0,
        "failed": 2,
        "total_api_calls": 2,
        "total_solutions": 2,
        "avg_solutions_per_input": 1.0,
    }


# Spec: the top-level totals cover every task that ran.
def test_top_level_totals_aggregate_the_tasks(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": PASSING * 3, "mmlu": FAILING * 2}
    )
    summary = result.summary
    assert summary["total"] == 5
    assert summary["passed"] == 3
    assert summary["failed"] == 2
    assert summary["total_api_calls"] == 5


# Spec: "include only tasks that actually ran".
def test_only_executed_tasks_appear(server, run_multi):
    result = run_multi(
        two_task_config(server.url), {"gsm8k": PASSING}, "--task", "gsm8k"
    )
    assert list(result.summary["tasks"]) == ["gsm8k"]
    assert result.summary["total"] == 1


# Spec: "per-task `total_api_calls` includes judge calls" -- and rejection
# attempts, as in Part 1.
def test_per_task_api_calls_count_every_attempt(servers, run_multi):
    server = servers(contents=["#### 1"], workers=1)
    config = make_multi_config(
        server.url,
        {
            "greedy_task": exact_match_task(),
            "rejection_task": exact_match_task(
                output_field="choice",
                generation={"scheme": "rejection", "temperature": 0.7, "n": 3},
            ),
        },
    )
    result = run_multi(config, {"greedy_task": PASSING, "rejection_task": PASSING})
    tasks = result.summary["tasks"]
    assert tasks["greedy_task"]["total_api_calls"] == 1
    assert tasks["rejection_task"]["total_api_calls"] == 3
    assert result.summary["total_api_calls"] == 4


# Spec: "within each task's output file, row order must still match input
# order".
def test_row_order_matches_input_order_per_task(servers, run_multi):
    server = servers(contents=["#### 42"], service_time=0.05)
    gsm8k = [{"question": f"g{i}", "answer": "42"} for i in range(12)]
    mmlu = [{"question": f"m{i}", "answer": "42"} for i in range(12)]
    result = run_multi(two_task_config(server.url), {"gsm8k": gsm8k, "mmlu": mmlu})
    assert [row["input"]["question"] for row in result.rows("gsm8k")] == [
        row["question"] for row in gsm8k
    ]
    assert [row["input"]["question"] for row in result.rows("mmlu")] == [
        row["question"] for row in mmlu
    ]


# Spec: "requests from different tasks may run concurrently and may be
# interleaved".
def test_tasks_run_concurrently(servers, run_multi):
    server = servers(contents=["#### 42"], service_time=0.3, workers=8)
    gsm8k = [{"question": f"g{i}", "answer": "42"} for i in range(16)]
    mmlu = [{"question": f"m{i}", "answer": "42"} for i in range(16)]
    result = run_multi(two_task_config(server.url), {"gsm8k": gsm8k, "mmlu": mmlu})
    assert result.exit_code == 0, result.stderr
    # 32 requests, 8 at a time, 0.3s each: ~1.2s concurrently, 9.6s serially.
    assert result.summary["elapsed_seconds"] < 4.0
    # The two tasks overlap: one of mmlu's requests arrives before the last of
    # gsm8k's, whichever task the event loop happens to dispatch first.
    seen = [payload["messages"][-1]["content"][0] for payload in server.payloads]
    assert seen.index("m") < len(seen) - 1 - seen[::-1].index("g")


# Spec: "throughput_rpm" counts every request the run made, across tasks.
def test_throughput_covers_all_tasks(servers, run_multi):
    server = servers(contents=["#### 42"], service_time=0.2, workers=8)
    rows = [{"question": f"q{i}", "answer": "42"} for i in range(20)]
    result = run_multi(two_task_config(server.url), {"gsm8k": rows, "mmlu": rows})
    assert result.summary["total_api_calls"] == 40
    # A sequential client would manage 300 rpm against a 0.2s service time;
    # the server's 8 workers make 2400 rpm available to the two tasks together.
    assert result.summary["throughput_rpm"] >= 600

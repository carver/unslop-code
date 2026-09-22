"""Run totals and the per-task breakdown."""

from summary import TaskResults, summarize


def meta(prompt_tokens=10, completion_tokens=5, **extra):
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, **extra}


def result(passed, output=True, metas=(), no_meta=False):
    """One finished row; `metas` lists the attempts when there was more than one."""
    return {
        "input": {},
        "output": {"solution": "x"} if output else None,
        "result": {"passed": passed},
        "meta": None if no_meta else (list(metas) or meta()),
    }


def test_counts_rows_tokens_and_throughput():
    task = TaskResults("demo", [result(True), result(False), result(True, output=False)], api_calls=7)
    assert summarize([task], elapsed_seconds=6.04) == {
        "total": 3,
        "passed": 2,
        "failed": 1,
        "total_prompt_tokens": 30,
        "total_completion_tokens": 15,
        "total_api_calls": 7,
        "elapsed_seconds": 6.0,
        "throughput_rpm": 69.5,
        "tasks": {"demo": {"total": 3, "passed": 2, "failed": 1, "total_api_calls": 7}},
    }


def test_rows_without_evaluation_count_as_passed_when_the_api_answered():
    task = TaskResults("demo", [result(None), result(None, output=False, no_meta=True)], api_calls=5)
    summary = summarize([task], elapsed_seconds=0.0)
    assert (summary["passed"], summary["failed"], summary["throughput_rpm"]) == (1, 1, 0.0)


def test_tasks_are_reported_separately_and_added_up():
    tasks = [
        TaskResults("gsm8k", [result(True), result(False)], api_calls=3),
        TaskResults("review", [result(True, metas=[meta(), meta(judge_meta=meta(1, 2))])], api_calls=4),
    ]
    summary = summarize(tasks, elapsed_seconds=10.0)

    assert summary["tasks"] == {
        "gsm8k": {"total": 2, "passed": 1, "failed": 1, "total_api_calls": 3},
        "review": {"total": 1, "passed": 1, "failed": 0, "total_api_calls": 4},
    }
    assert (summary["total"], summary["passed"], summary["total_api_calls"]) == (3, 2, 7)
    # The judge call's tokens are counted alongside the generation's.
    assert (summary["total_prompt_tokens"], summary["total_completion_tokens"]) == (41, 22)


def test_rows_the_api_never_answered_contribute_no_tokens():
    summary = summarize([TaskResults("demo", [result(False, output=False, no_meta=True)], api_calls=4)],
                        elapsed_seconds=1.0)
    assert summary["total_prompt_tokens"] == 0

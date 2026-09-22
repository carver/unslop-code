"""Per-row generation schemes and summary aggregation."""

import asyncio
from dataclasses import replace

from api import Completion
from config import GenerationConfig, PromptConfig, TaskConfig
from evaluation import EvaluationConfig
from runner import process_row, summarize

ROW = {"question": "2 + 3?", "answer": "5"}
MESSAGES = [{"role": "user", "content": "2 + 3?"}]
EVALUATION = EvaluationConfig(type="exact_match", extract="last_number", answer_field="answer")

TASK = TaskConfig(
    name="demo",
    api_url="http://localhost:8000",
    model="gpt-4",
    rpm=60,
    prompt=PromptConfig(system="", user="{question}"),
    generation=GenerationConfig(scheme="greedy", temperature=0.0, max_tokens=64, n=1),
    evaluation=EVALUATION,
    output_field="solution",
)


def meta(index):
    return {
        "model": "gpt-4",
        "prompt_tokens": 10,
        "completion_tokens": index,
        "total_tokens": 10 + index,
        "latency_ms": 5,
        "finish_reason": "stop",
    }


def completion(answer, index=1):
    return Completion(text=f"working\n#### {answer}", meta=meta(index))


class StubClient:
    """Hands out prepared responses in order; None stands for an exhausted retry budget."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, temperature, max_tokens):
        self.calls.append((temperature, max_tokens))
        return self.responses.pop(0)


def run(task, client):
    return asyncio.run(process_row(task, client, ROW, MESSAGES))


def rejection_task(n):
    return replace(TASK, generation=GenerationConfig("rejection", 0.8, 64, n))


def test_greedy_keeps_the_single_response():
    client = StubClient(completion("5"))
    result = run(TASK, client)
    assert result["input"] is ROW
    assert result["output"] == {"solution": "working\n#### 5"}
    assert result["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert result["meta"] == meta(1)
    assert client.calls == [(0.0, 64)]


def test_greedy_keeps_a_failing_response():
    result = run(TASK, StubClient(completion("7")))
    assert result["output"] == {"solution": "working\n#### 7"}
    assert result["result"] == {"passed": False, "extracted_answer": "7", "attempts": 1}


def test_sample_does_not_resample_on_failure():
    task = replace(TASK, generation=GenerationConfig("sample", 0.9, 64, 4))
    client = StubClient(completion("7"), completion("5"))
    assert run(task, client)["result"]["attempts"] == 1
    assert client.calls == [(0.9, 64)]


def test_no_evaluation_leaves_passed_unset():
    result = run(replace(TASK, evaluation=None), StubClient(completion("7")))
    assert result["result"] == {"passed": None, "extracted_answer": None, "attempts": 1}


def test_rejection_stops_at_the_first_passing_response():
    client = StubClient(completion("7", 1), completion("8", 2), completion("5", 3))
    result = run(rejection_task(5), client)
    assert result["output"] == {"solution": "working\n#### 5"}
    assert result["result"] == {"passed": True, "extracted_answer": "5", "attempts": 3}
    assert result["meta"] == [meta(1), meta(2), meta(3)]
    assert client.calls == [(0.8, 64)] * 3


def test_rejection_reports_a_single_meta_object_for_one_attempt():
    result = run(rejection_task(3), StubClient(completion("5")))
    assert result["meta"] == meta(1)


def test_rejection_exhausts_its_attempts():
    client = StubClient(*(completion("7", index) for index in range(1, 4)))
    result = run(rejection_task(3), client)
    assert result["output"] is None
    assert result["result"] == {"passed": False, "extracted_answer": None, "attempts": 3}
    assert len(result["meta"]) == 3


def test_failed_api_call_produces_a_null_row():
    result = run(TASK, StubClient(None))
    assert result["output"] is None
    assert result["result"] == {"passed": False, "extracted_answer": None, "attempts": 1}
    assert result["meta"] is None


def test_summary_counts_rows_tokens_and_throughput():
    results = [
        run(TASK, StubClient(completion("5"))),
        run(TASK, StubClient(completion("7"))),
        run(rejection_task(2), StubClient(completion("7", 1), completion("5", 2))),
        run(TASK, StubClient(None)),
    ]
    assert summarize(results, api_calls=7, elapsed_seconds=6.04) == {
        "total": 4,
        "passed": 2,
        "failed": 2,
        "total_prompt_tokens": 40,
        "total_completion_tokens": 5,
        "total_api_calls": 7,
        "elapsed_seconds": 6.0,
        "throughput_rpm": 69.5,
    }


def test_rows_without_evaluation_count_as_passed_when_the_api_answered():
    task = replace(TASK, evaluation=None)
    results = [run(task, StubClient(completion("7"))), run(task, StubClient(None))]
    summary = summarize(results, api_calls=5, elapsed_seconds=0.0)
    assert (summary["passed"], summary["failed"], summary["throughput_rpm"]) == (1, 1, 0.0)

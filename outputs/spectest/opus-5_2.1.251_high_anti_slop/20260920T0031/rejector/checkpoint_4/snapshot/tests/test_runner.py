"""Per-row generation schemes, evaluation dispatch and result rows."""

import asyncio
from dataclasses import replace

from config import GenerationConfig, PromptConfig, TaskConfig
from endpoints import Completion
from evaluation import EvaluationConfig
from judge import Judge
from runner import TaskWorker
from schedule import attempt_plan

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

JUDGE_EVALUATION = EvaluationConfig(
    type="llm_judge",
    extract="first_number",
    judge_prompt=PromptConfig(system="", user="Rate {__response__}"),
    threshold=7,
    model="judge-model",
)


def meta(index, **extra):
    return {
        "model": "gpt-4",
        "prompt_tokens": 10,
        "completion_tokens": index,
        "total_tokens": 10 + index,
        "latency_ms": 5,
        "finish_reason": "stop",
        **extra,
    }


def completion(answer, index=1):
    return Completion(text=f"working\n#### {answer}", meta=meta(index))


class StubClient:
    """Hands out prepared responses in order; None stands for an exhausted retry budget."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.prompts = []

    async def complete(self, messages, model, temperature, max_tokens):
        self.calls.append((model, temperature, max_tokens))
        self.prompts.append(messages)
        return self.responses.pop(0)


def run(task, client, judge=None):
    worker = TaskWorker(task, client, judge, attempt_plan(task, setups=()))
    return asyncio.run(worker.run_row(ROW, MESSAGES))


def rejection_task(n):
    return replace(TASK, generation=GenerationConfig("rejection", 0.8, 64, n))


def test_greedy_keeps_the_single_response():
    client = StubClient(completion("5"))
    result = run(TASK, client)
    assert result["input"] is ROW
    assert result["output"] == {"solution": "working\n#### 5"}
    assert result["result"] == {"passed": True, "extracted_answer": "5", "attempts": 1}
    assert result["meta"] == meta(1)
    assert client.calls == [("gpt-4", 0.0, 64)]


def test_greedy_keeps_a_failing_response():
    result = run(TASK, StubClient(completion("7")))
    assert result["output"] == {"solution": "working\n#### 7"}
    assert result["result"] == {"passed": False, "extracted_answer": "7", "attempts": 1}


def test_sample_does_not_resample_on_failure():
    task = replace(TASK, generation=GenerationConfig("sample", 0.9, 64, 4))
    client = StubClient(completion("7"), completion("5"))
    assert run(task, client)["result"]["attempts"] == 1
    assert client.calls == [("gpt-4", 0.9, 64)]


def test_no_evaluation_leaves_passed_unset():
    result = run(replace(TASK, evaluation=None), StubClient(completion("7")))
    assert result["result"] == {"passed": None, "extracted_answer": None, "attempts": 1}


def test_rejection_stops_at_the_first_passing_response():
    client = StubClient(completion("7", 1), completion("8", 2), completion("5", 3))
    result = run(rejection_task(5), client)
    assert result["output"] == {"solution": "working\n#### 5"}
    assert result["result"] == {"passed": True, "extracted_answer": "5", "attempts": 3}
    assert result["meta"] == [meta(1), meta(2), meta(3)]
    assert client.calls == [("gpt-4", 0.8, 64)] * 3


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


def test_judge_score_and_meta_are_recorded():
    task = replace(TASK, evaluation=JUDGE_EVALUATION)
    client = StubClient(completion("5"), Completion(text="8", meta=meta(2)))
    result = run(task, client, Judge(client, JUDGE_EVALUATION, max_tokens=64))

    assert result["result"] == {"passed": True, "extracted_answer": "8", "attempts": 1, "judge_score": 8}
    assert result["meta"] == meta(1, judge_meta=meta(2))
    assert client.calls[1] == ("judge-model", 0.0, 64)


def test_script_evaluation_decides_a_row():
    evaluation = EvaluationConfig(type="script", extract="full", command_template="test -n '{__response__}'")
    result = run(replace(TASK, evaluation=evaluation), StubClient(completion("5")))
    assert result["result"] == {"passed": True, "extracted_answer": None, "attempts": 1}

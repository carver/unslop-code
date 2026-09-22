"""Rows of a task that must answer with JSON matching an `output_schema`."""

import asyncio
from dataclasses import replace

from config import GenerationConfig, PromptConfig, TaskConfig
from endpoints import Completion
from evaluation import EvaluationConfig
from runner import TaskWorker
from schedule import attempt_plan

ROW = {"question": "Add two numbers", "answer": "sum"}
MESSAGES = [{"role": "user", "content": "Add two numbers"}]

SCHEMA = {
    "type": "object",
    "required": ["code", "explanation"],
    "properties": {"code": {"type": "string"}, "explanation": {"type": "string"}},
}

TASK = TaskConfig(
    name="code_gen",
    api_url="http://localhost:8000",
    model="gpt-4",
    prompt=PromptConfig(system="", user="{question}"),
    generation=GenerationConfig(scheme="greedy", temperature=0.0, max_tokens=64, n=1),
    evaluation=None,
    output_field="code",
    output_schema=SCHEMA,
)

VALID = '{"code": "def add(a, b): return a + b", "explanation": "Simple addition function"}'
MISSING = '{"code": "def add(a, b): return a + b"}'


def meta(index=1):
    return {"model": "gpt-4", "prompt_tokens": 10, "completion_tokens": index,
            "total_tokens": 10 + index, "latency_ms": 5, "finish_reason": "stop"}


class StubClient:
    """Hands out prepared response texts in order."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    async def complete(self, messages, model, temperature, max_tokens):
        self.calls += 1
        return Completion(text=self.texts.pop(0), meta=meta(self.calls))


def run(task, client):
    worker = TaskWorker(task, client, None, attempt_plan(task, setups=()))
    return asyncio.run(worker.run_row(ROW, MESSAGES))


def test_a_valid_response_is_stored_as_its_parsed_value():
    result = run(TASK, StubClient(VALID))
    assert result["output"] == {"code": {"code": "def add(a, b): return a + b",
                                        "explanation": "Simple addition function"}}
    assert result["result"]["passed"] is True
    assert result["result"]["schema_valid"] is True
    assert "schema_error" not in result["result"]


def test_a_schema_failure_empties_the_row_and_says_why():
    result = run(TASK, StubClient(MISSING))
    assert result["output"] is None
    assert result["result"]["passed"] is False
    assert result["result"]["schema_valid"] is False
    assert result["result"]["schema_error"] == "Missing required field: explanation"


def test_invalid_json_fails_the_same_way():
    result = run(TASK, StubClient("Sure! Here is the code."))
    assert (result["output"], result["result"]["schema_valid"]) == (None, False)


def test_evaluation_is_skipped_when_the_schema_fails():
    evaluation = EvaluationConfig(type="contains", extract="full", answer_field="answer")
    result = run(replace(TASK, evaluation=evaluation), StubClient(MISSING))
    assert (result["result"]["passed"], result["result"]["extracted_answer"]) == (False, None)


def test_evaluation_still_decides_a_valid_response():
    evaluation = EvaluationConfig(type="contains", extract="full", answer_field="answer")
    result = run(replace(TASK, evaluation=evaluation), StubClient(VALID))
    assert (result["result"]["passed"], result["result"]["schema_valid"]) == (False, True)


def test_rejection_retries_a_schema_failure_without_any_evaluation():
    task = replace(TASK, generation=GenerationConfig("rejection", 0.8, 64, n=3))
    client = StubClient("not json", MISSING, VALID)
    result = run(task, client)

    assert client.calls == 3
    assert result["result"]["attempts"] == 3
    assert result["output"]["code"]["explanation"] == "Simple addition function"
    assert result["result"]["schema_valid"] is True


def test_rejection_that_never_validates_writes_a_null_row():
    task = replace(TASK, generation=GenerationConfig("rejection", 0.8, 64, n=2))
    result = run(task, StubClient(MISSING, "not json"))
    assert (result["output"], result["result"]["passed"]) == (None, False)

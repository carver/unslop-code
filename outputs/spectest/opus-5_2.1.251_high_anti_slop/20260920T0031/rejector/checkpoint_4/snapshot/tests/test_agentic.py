"""The agentic loop: tool execution, iteration accounting and the rows it writes."""

import asyncio
from dataclasses import replace

from test_runner import EVALUATION, TASK, meta

from agentic import build_loop
from config import GenerationConfig
from endpoints import ChatEndpoint, Completion
from icl import IclConfig, RenderedSetup
from runner import TaskWorker
from schedule import attempt_plan
from tools import ToolCall, load_tools

ROW = {"question": "What is the total revenue for Q1 and Q2?", "answer": "2730000"}
MESSAGES = [
    {"role": "system", "content": "Use the provided tools."},
    {"role": "user", "content": ROW["question"]},
]

TOOL_DEFINITIONS = [
    {
        "name": "lookup",
        "description": "Look up a value in the database by key",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        "handler": {
            "type": "static_map",
            "mapping": {"revenue_q1": "1250000", "revenue_q2": "1480000", "employees": "142"},
            "default": "KEY_NOT_FOUND",
        },
    }
]

ANSWER = "The total revenue for Q1 and Q2 is 2730000."


def agentic_task(num_solutions=1, max_iterations=10, evaluation=EVALUATION, icl=None):
    return replace(
        TASK,
        generation=GenerationConfig("agentic", 0.0, 64, n=1, max_iterations=max_iterations),
        evaluation=evaluation,
        output_field="answer",
        tools=load_tools(TOOL_DEFINITIONS, "task.tools"),
        num_solutions=num_solutions,
        icl=icl,
    )


def detail(index, finish_reason="stop"):
    """The per-request entry `meta.iterations_detail` records for one iteration."""
    return {
        "prompt_tokens": 10,
        "completion_tokens": index,
        "total_tokens": 10 + index,
        "latency_ms": 5,
        "finish_reason": finish_reason,
    }


def asks_for(*keys, index=1):
    """A response requesting one `lookup` call per key."""
    calls = tuple(ToolCall(id=f"call_{n}", name="lookup", args={"key": key}) for n, key in enumerate(keys, 1))
    return Completion(text=None, meta=meta(index, finish_reason="tool_calls"), tool_calls=calls)


def answers(text=ANSWER, index=1):
    return Completion(text=text, meta=meta(index))


class StubClient:
    """Hands out prepared completions in order, recording what each request was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.conversations = []
        self.tools = []

    async def complete(self, messages, model, temperature, max_tokens, tools=()):
        self.conversations.append(list(messages))
        self.tools.append(tools)
        return self.responses.pop(0)


def run(task, client, setups=()):
    loop = build_loop(task, client, ChatEndpoint())
    worker = TaskWorker(task, client, None, attempt_plan(task, setups), loop)
    return asyncio.run(worker.run_row(ROW, MESSAGES))


def aggregated(result):
    """A row's agentic metadata with its wall-clock latency dropped."""
    return {key: value for key, value in result["meta"].items() if key != "latency_ms"}


def test_a_loop_runs_its_tools_then_answers():
    client = StubClient(asks_for("revenue_q1", "revenue_q2", index=1), answers(index=2))
    result = run(agentic_task(), client)

    assert result["output"] == {"answer": ANSWER}
    assert result["result"] == {
        "passed": True,
        "extracted_answer": "2730000",
        "attempts": 1,
        "iterations": 2,
        "tool_calls": [
            {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q1"}, "result": "1250000"},
            {"iteration": 1, "tool": "lookup", "args": {"key": "revenue_q2"}, "result": "1480000"},
        ],
    }


def test_metadata_aggregates_every_iteration():
    client = StubClient(asks_for("employees", index=1), asks_for("revenue_q1", index=2), answers(index=3))
    result = run(agentic_task(), client)

    assert result["result"]["iterations"] == 3
    assert aggregated(result) == {
        "total_prompt_tokens": 30,
        "total_completion_tokens": 6,
        "total_tokens": 36,
        "finish_reason": "stop",
        "iterations_detail": [detail(1, "tool_calls"), detail(2, "tool_calls"), detail(3)],
    }
    assert result["meta"]["latency_ms"] >= 0


def test_tool_results_are_fed_back_into_the_conversation():
    client = StubClient(asks_for("employees"), answers("The company has 142 employees."))
    run(agentic_task(), client)

    assert [message["role"] for message in client.conversations[1]] == ["system", "user", "assistant", "tool"]
    assert client.conversations[1][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "142"}
    assert [tool.name for tool in client.tools[0]] == ["lookup"]


def test_an_unfinished_loop_stops_at_its_iteration_limit():
    client = StubClient(*(asks_for("employees", index=index) for index in range(1, 4)))
    result = run(agentic_task(max_iterations=3), client)

    assert result["output"] is None
    assert result["result"]["passed"] is False
    assert result["result"]["extracted_answer"] is None
    assert result["result"]["iterations"] == 3
    assert len(result["result"]["tool_calls"]) == 3
    assert result["meta"]["finish_reason"] == "max_iterations"
    assert len(result["meta"]["iterations_detail"]) == 3


def test_a_loop_without_evaluation_leaves_passed_unset():
    client = StubClient(asks_for("employees"), answers())
    result = run(agentic_task(evaluation=None), client)
    assert result["result"]["passed"] is None
    assert result["result"]["iterations"] == 2


def test_a_spent_retry_budget_ends_the_row_without_an_output():
    result = run(agentic_task(), StubClient(None))
    assert result["output"] is None
    assert result["meta"] is None
    assert result["result"] == {
        "passed": False,
        "extracted_answer": None,
        "attempts": 1,
        "iterations": 0,
        "tool_calls": [],
    }


def test_num_solutions_runs_one_independent_loop_per_solution():
    client = StubClient(answers(index=1), answers(index=2))
    result = run(agentic_task(num_solutions=2), client)

    assert result["output"] == [{"answer": ANSWER, "icl_setup": None}] * 2
    assert result["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [entry["iterations_detail"] for entry in result["meta"]] == [[detail(1)], [detail(2)]]
    assert [entry["evaluation_passed"] for entry in result["meta"]] == [True, True]
    assert [entry["total_tokens"] for entry in result["meta"]] == [11, 12]


def test_the_list_format_counts_loops_not_requests():
    client = StubClient(asks_for("employees", index=1), answers(index=2), answers(index=3))
    result = run(agentic_task(num_solutions=2), client)

    assert result["result"]["attempts"] == 2
    assert [entry["finish_reason"] for entry in result["meta"]] == ["stop", "stop"]


def test_the_list_format_without_evaluation_counts_emitted_outputs():
    client = StubClient(*(asks_for("employees", index=index) for index in range(1, 4)), answers(index=4))
    result = run(agentic_task(num_solutions=2, max_iterations=3, evaluation=None), client)

    assert result["output"] == [{"answer": ANSWER, "icl_setup": None}]
    assert result["result"] == {"passed": 1, "failed": 1, "attempts": 2}
    assert [entry["evaluation_passed"] for entry in result["meta"]] == [None, None]
    assert [entry["finish_reason"] for entry in result["meta"]] == ["max_iterations", "stop"]


def test_icl_examples_open_every_loop():
    setups = (RenderedSetup(name="cot", messages=({"role": "user", "content": "demo"},)),)
    task = agentic_task(icl=IclConfig(setups=(), strategy="fixed", k=None))
    client = StubClient(asks_for("employees"), answers())
    result = run(task, client, setups)

    assert [message["content"] for message in client.conversations[0]] == [
        "Use the provided tools.",
        "demo",
        ROW["question"],
    ]
    assert result["meta"][0]["icl_setup"] == "cot"


def test_loops_of_different_rows_overlap():
    """Three rows each needing two requests must not serialise into six sequential calls."""
    in_flight = 0
    peak = 0

    class SlowClient(StubClient):
        async def complete(self, messages, model, temperature, max_tokens, tools=()):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return asks_for("employees") if len(messages) == 2 else answers()

    task = agentic_task()

    async def rows():
        client = SlowClient()
        loop = build_loop(task, client, ChatEndpoint())
        worker = TaskWorker(task, client, None, attempt_plan(task, ()), loop)
        return await asyncio.gather(*(worker.run_row(ROW, MESSAGES) for _ in range(3)))

    results = asyncio.run(rows())
    assert all(result["result"]["iterations"] == 2 for result in results)
    assert peak == 3

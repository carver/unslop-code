"""The agentic generation loop: tool rounds until the model answers.

One loop owns one conversation.  It alternates API requests with local tool
execution until the model replies with text instead of tool calls, or until
the task's `max_iterations` budget of requests is spent.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from .api import Completion, ModelClient, ToolInvocation
from .config import TaskConfig
from .icl import IclExample
from .prompts import build_messages
from .tools import Handler

ITERATION_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason")
MAX_ITERATIONS_REASON = "max_iterations"
REQUEST_FAILED_REASON = "error"


@dataclass(frozen=True)
class LoopResult:
    """What one agentic loop produced.

    `output` is None when the loop ended without final text; `meta` is the
    row's aggregated metadata, including one detail entry per API request.
    """

    output: str | None
    iterations: int
    tool_calls: list[dict]
    meta: dict


async def run_loop(
    client: ModelClient, task: TaskConfig, row: dict, examples: Sequence[IclExample] = ()
) -> LoopResult:
    """Drive one conversation until the model answers or the budget runs out."""
    conversation = build_messages(task.prompt, row, examples=examples)
    handlers = {tool.name: tool.handler for tool in task.tools}
    started = time.perf_counter()
    details: list[dict] = []
    records: list[dict] = []

    for iteration in range(1, task.generation.max_iterations + 1):
        completion = await client.complete(conversation, tools=task.tools)
        if completion is None:
            return _result(None, records, details, REQUEST_FAILED_REASON, started)

        details.append({key: completion.meta[key] for key in ITERATION_FIELDS})
        if not completion.tool_calls:
            reason = completion.meta["finish_reason"] or "stop"
            return _result(completion.text, records, details, reason, started)

        records += await _run_tools(handlers, completion, conversation, iteration)

    return _result(None, records, details, MAX_ITERATIONS_REASON, started)


async def _run_tools(
    handlers: dict[str, Handler], completion: Completion, conversation: list[dict], iteration: int
) -> list[dict]:
    """Execute one response's tool calls and extend the conversation with them."""
    conversation.append(completion.message)

    records = []
    for call in completion.tool_calls:
        result = await _invoke(handlers, call)
        records.append(
            {"iteration": iteration, "tool": call.name, "args": call.arguments, "result": result}
        )
        conversation.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return records


async def _invoke(handlers: dict[str, Handler], call: ToolInvocation) -> str:
    handler = handlers.get(call.name)
    if handler is None:
        return f"ERROR: unknown tool '{call.name}'"
    return await handler.invoke(call.arguments)


def _result(
    output: str | None, records: list[dict], details: list[dict], reason: str, started: float
) -> LoopResult:
    """Close a loop, aggregating the metadata of every request it made."""
    meta = {
        "total_prompt_tokens": sum(detail["prompt_tokens"] for detail in details),
        "total_completion_tokens": sum(detail["completion_tokens"] for detail in details),
        "total_tokens": sum(detail["total_tokens"] for detail in details),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "finish_reason": reason,
        "iterations_detail": details,
    }
    return LoopResult(output=output, iterations=len(details), tool_calls=records, meta=meta)

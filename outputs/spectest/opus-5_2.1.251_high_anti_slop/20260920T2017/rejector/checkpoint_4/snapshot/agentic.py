"""The agentic loop: call tools until the model answers, then report the run.

Each pass through the loop is one API request. A response holding tool calls is
appended to the conversation along with every result, and the loop goes round
again; a response holding only text ends it. The loop is a plain coroutine, so
the rows of a batch stay interleaved rather than taking turns.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from client import ApiClient, Completion
from config import GenerationConfig
from prompts import RenderedPrompt
from tools import ToolCall, ToolConfig, invoke

#: Per-request metadata kept in `iterations_detail`; `model` is reported once.
DETAIL_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason")


@dataclass(frozen=True)
class Generation:
    """What one attempt produced: a single request, or a whole agentic loop.

    `text` is None when a loop ran out of iterations before the model answered.
    `iterations` and `tool_calls` stay unset for the schemes that make a single
    request, whose metadata the API already reports per call.
    """

    text: str | None
    meta: dict[str, Any]
    iterations: int | None = None
    tool_calls: list[dict[str, Any]] | None = None


async def run_agentic(
    client: ApiClient,
    generation: GenerationConfig,
    tools: tuple[ToolConfig, ...],
    prompt: RenderedPrompt,
) -> Generation | None:
    """Drive one agentic loop to a final answer, or to its iteration limit.

    Returns None if the API stopped answering part way through, which the row
    records the same way as any other unanswered attempt.
    """
    messages = prompt.messages()
    details: list[dict[str, Any]] = []
    recorded: list[dict[str, Any]] = []
    started = time.monotonic()

    for iteration in range(1, generation.max_iterations + 1):
        completion = await client.complete(
            messages, generation.temperature, generation.max_tokens, tools=tools
        )
        if completion is None:
            return None
        details.append({field: completion.meta[field] for field in DETAIL_FIELDS})
        if not completion.tool_calls:
            return _finish(completion.text, details, recorded, iteration, started)

        results, calls = await _run_tools(tools, completion.tool_calls, iteration)
        messages.append(_assistant_turn(completion))
        messages.extend(results)
        recorded.extend(calls)

    return _finish(None, details, recorded, generation.max_iterations, started)


async def _run_tools(
    tools: tuple[ToolConfig, ...], requested: tuple[ToolCall, ...], iteration: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute one iteration's calls, returning their tool messages and records."""
    results = await asyncio.gather(*(invoke(tools, call) for call in requested))
    messages = [
        {"role": "tool", "tool_call_id": call.id, "content": result}
        for call, result in zip(requested, results)
    ]
    records = [
        {"iteration": iteration, "tool": call.name, "args": call.arguments, "result": result}
        for call, result in zip(requested, results)
    ]
    return messages, records


def _assistant_turn(completion: Completion) -> dict[str, Any]:
    """The assistant message replaying the calls the model has just asked for."""
    return {
        "role": "assistant",
        "content": completion.text,
        "tool_calls": [call.as_message() for call in completion.tool_calls],
    }


def _finish(
    text: str | None,
    details: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    iterations: int,
    started: float,
) -> Generation:
    """Aggregate the loop's requests into the one result a row records."""
    return Generation(
        text=text,
        meta={
            "total_prompt_tokens": sum(detail["prompt_tokens"] for detail in details),
            "total_completion_tokens": sum(detail["completion_tokens"] for detail in details),
            "total_tokens": sum(detail["total_tokens"] for detail in details),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "finish_reason": "stop" if text is not None else "max_iterations",
            "iterations_detail": details,
        },
        iterations=iterations,
        tool_calls=tool_calls,
    )

"""The agentic loop: request, run the tools the model asked for, repeat.

One loop is one solution. It keeps its own conversation and its own metadata,
and awaits each request in turn, so several rows -- and several solutions of
one row -- still have their requests in flight at the same time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .api import Channel
from .config import TaskConfig
from .icl import IclSetup
from .inputs import render_messages
from .tools import ToolCall, find_tool, invoke_tool

FINAL = "stop"
EXHAUSTED = "max_iterations"
FAILED = "error"
ITERATION_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "finish_reason",
)


@dataclass(frozen=True)
class AgenticRun:
    """One finished loop: its final text, its tool calls, and its metadata."""

    content: str | None
    iterations: int
    tool_calls: list[dict]
    meta: dict


async def run_loop(
    row: dict, task: TaskConfig, channel: Channel, setup: IclSetup | None = None
) -> AgenticRun:
    """Run one agentic loop for `row` until the model answers or runs out.

    The loop occupies one concurrency slot from its first request to its last,
    so a task's `max_concurrent` counts loops rather than their iterations.
    """
    async with channel.generation.limiter.slots:
        return await _iterate(row, task, channel, setup)


async def _iterate(
    row: dict, task: TaskConfig, channel: Channel, setup: IclSetup | None
) -> AgenticRun:
    """Request, run the tools the model asked for, and repeat."""
    conversation = render_messages(row, task, setup)
    started = time.monotonic()
    iterations: list[dict] = []
    records: list[dict] = []
    content, reason = None, FAILED

    for iteration in range(1, task.generation.max_iterations + 1):
        completion = await channel.client.complete(
            conversation,
            task.generation.temperature,
            channel.generation,
            task.tools,
            hold_slot=False,
        )
        if completion is None:
            break

        iterations.append({key: completion.meta[key] for key in ITERATION_FIELDS})
        if not completion.tool_calls:
            content, reason = completion.content, FINAL
            break

        executed = await _execute(completion.tool_calls, task, iteration)
        records += [record for record, _ in executed]
        conversation = [*conversation, completion.message, *(turn for _, turn in executed)]
        reason = EXHAUSTED

    return AgenticRun(content, len(iterations), records, _meta(iterations, reason, started))


async def _execute(
    calls: tuple[ToolCall, ...], task: TaskConfig, iteration: int
) -> list[tuple[dict, dict]]:
    """Run each call in order, returning its record and its result turn."""
    executed = []
    for call in calls:
        result = await _invoke(call, task)
        executed.append(
            (
                {
                    "iteration": iteration,
                    "tool": call.name,
                    "args": call.args,
                    "result": result,
                },
                {"role": "tool", "tool_call_id": call.id, "content": result},
            )
        )
    return executed


async def _invoke(call: ToolCall, task: TaskConfig) -> str:
    """The handler's answer to one call, or an error the model can read."""
    tool = find_tool(task.tools, call.name)
    if tool is None:
        return f"ERROR: unknown tool {call.name!r}"
    return await invoke_tool(tool, call.args)


def _meta(iterations: list[dict], reason: str, started: float) -> dict:
    """The loop's aggregated metadata, with its per-iteration detail."""
    return {
        "total_prompt_tokens": _total(iterations, "prompt_tokens"),
        "total_completion_tokens": _total(iterations, "completion_tokens"),
        "total_tokens": _total(iterations, "total_tokens"),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "finish_reason": reason,
        "iterations_detail": iterations,
    }


def _total(iterations: list[dict], field: str) -> int:
    return sum(iteration[field] or 0 for iteration in iterations)

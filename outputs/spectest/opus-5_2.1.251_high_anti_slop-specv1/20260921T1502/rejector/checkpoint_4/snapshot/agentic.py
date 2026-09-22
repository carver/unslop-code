"""The agentic generation loop: tool calls until the model answers in text.

One loop sends a request, runs whatever tools the reply asked for, feeds their
results back and repeats. It ends on a reply that carries text and no tool
call, or on the iteration limit, which produces no output at all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from client import ApiClient
from icl import Setup
from jobs import Job
from tools import call_tool

# The per request metadata an iteration contributes to `iterations_detail`.
ITERATION_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "finish_reason",
)


@dataclass(frozen=True)
class Loop:
    """What one agentic run produced.

    `meta` aggregates every request the loop made and is None when one of them
    failed outright, matching a plain attempt that never got an answer.
    """

    text: str | None
    meta: dict | None
    tool_calls: list[dict]
    iterations: int


async def run_loop(client: ApiClient, job: Job, index: int, setup: Setup | None) -> Loop:
    """Run one row through the loop, starting from its prompt and the given ICL setup."""
    config = job.config
    tools = {tool.name: tool for tool in config.tools}
    messages = list(job.messages_for(index, setup))
    started = time.monotonic()
    details: list[dict] = []
    calls: list[dict] = []

    for iteration in range(1, config.generation.max_iterations + 1):
        attempt = await client.complete(messages, tools=config.tools)
        if attempt.meta is None:
            return Loop(None, None, calls, iteration)
        details.append({field: attempt.meta[field] for field in ITERATION_FIELDS})

        if not attempt.tool_calls:
            return Loop(attempt.text, _meta(details, started), calls, iteration)

        messages.append(client.assistant_turn(attempt))
        results = [(call, await call_tool(tools, call)) for call in attempt.tool_calls]
        calls.extend(
            {"iteration": iteration, "tool": call.name, "args": call.arguments, "result": result}
            for call, result in results
        )
        messages.extend(client.tool_turns(results))

    return Loop(None, _meta(details, started, "max_iterations"), calls, len(details))


def _meta(details: list[dict], started: float, finish_reason: str | None = None) -> dict:
    """Totals across the loop's requests; the last one's finish reason is the loop's."""
    return {
        "total_prompt_tokens": sum(entry["prompt_tokens"] for entry in details),
        "total_completion_tokens": sum(entry["completion_tokens"] for entry in details),
        "total_tokens": sum(entry["total_tokens"] for entry in details),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "finish_reason": finish_reason or details[-1]["finish_reason"],
        "iterations_detail": details,
    }

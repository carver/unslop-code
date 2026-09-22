"""The agentic loop: model requests interleaved with tool calls."""

from __future__ import annotations

import time
from dataclasses import dataclass

from rejlib.api import ApiClient
from rejlib.config import TaskConfig
from rejlib.tools import Invocation, parse_calls, run_tool

#: "use `finish_reason: "max_iterations"`" when the loop runs out of requests.
MAX_ITERATIONS = "max_iterations"

#: The per-request fields `meta.iterations_detail` records (T55).
ITERATION_FIELDS = (
    "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason",
)


@dataclass
class AgenticRun:
    """What one loop produced: its final text, and everything it did on the way."""

    content: str | None
    #: "the number of API requests in the loop"
    iterations: int
    tool_calls: list[dict]
    #: Totals, wall-clock latency and per-iteration detail for the whole loop.
    meta: dict

    @property
    def hit_limit(self) -> bool:
        """Whether the loop stopped because it ran out of iterations."""
        return self.meta["finish_reason"] == MAX_ITERATIONS


async def run_loop(client: ApiClient, config: TaskConfig,
                   messages: list[dict]) -> AgenticRun:
    """Call the model until it answers in text, or the iteration budget runs out.

    ``messages`` is the initial conversation. Every iteration that asks for tools
    appends the assistant tool-call message and one message per tool result, so
    the next request sees what the tools returned. A request whose retries were
    exhausted ends the loop without an output but without the limit label (T58).

    The loop holds one concurrency slot for its entire lifetime, so a long loop
    occupies exactly as much of `max_concurrent` as a single request would.
    """
    conversation = list(messages)
    details: list[dict] = []
    records: list[dict] = []
    started = time.monotonic()

    async with client.scheduler.slot():
        for iteration in range(1, config.generation.max_iterations + 1):
            attempt = await client.complete(conversation, config.tools)
            details.append({key: attempt.meta[key] for key in ITERATION_FIELDS})

            calls = parse_calls(config.api_type, attempt.message) if attempt.message else []
            if not calls:
                return _run(attempt.content, details, records, started,
                            details[-1]["finish_reason"])

            conversation.append(attempt.message)
            for call in calls:
                result = await run_tool(config.tools, call.name, call.args)
                records.append({"iteration": iteration, "tool": call.name,
                                "args": call.args, "result": result})
                conversation.append(_tool_message(call, result))
    return _run(None, details, records, started, MAX_ITERATIONS)


def _run(content: str | None, details: list[dict], records: list[dict],
         started: float, finish_reason: str | None) -> AgenticRun:
    """Close one loop, aggregating its requests into the row's metadata."""
    return AgenticRun(
        content=content,
        iterations=len(details),
        tool_calls=records,
        meta={
            "total_prompt_tokens": sum(entry["prompt_tokens"] for entry in details),
            "total_completion_tokens": sum(entry["completion_tokens"] for entry in details),
            "total_tokens": sum(entry["total_tokens"] for entry in details),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "finish_reason": finish_reason,
            "iterations_detail": details,
        },
    )


def _tool_message(call: Invocation, result: str) -> dict:
    """The turn carrying one tool's result; chat mode ties it to the call id (T68)."""
    if call.id is None:
        return {"role": "tool", "content": result}
    return {"role": "tool", "tool_call_id": call.id, "content": result}

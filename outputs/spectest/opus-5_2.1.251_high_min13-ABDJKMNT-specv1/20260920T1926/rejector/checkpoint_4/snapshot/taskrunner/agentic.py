"""The agentic loop: alternating model turns and tool executions.

One loop is one solution. It keeps sending the growing conversation back to
the model until a response arrives with text and no tool calls, or until the
task's `max_iterations` requests have been spent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .api import CallMeta, CallResult, ModelClient
from .config import TaskConfig
from .tools import ToolCall, ToolInvocation, execute_calls

STOP = "stop"
MAX_ITERATIONS = "max_iterations"


@dataclass(frozen=True)
class AgenticOutcome:
    """Everything one loop produced, before it is shaped into JSON."""

    text: str | None
    iterations: int
    tool_calls: list[ToolInvocation]
    metas: list[CallMeta]
    latency_ms: int
    finish_reason: str | None
    requests: int

    @property
    def hit_limit(self) -> bool:
        return self.finish_reason == MAX_ITERATIONS


async def run_loop(
    client: ModelClient, config: TaskConfig, messages: Sequence[Mapping[str, Any]]
) -> AgenticOutcome:
    """Drive one conversation to a final answer or to the iteration limit."""
    conversation = list(messages)
    invocations: list[ToolInvocation] = []
    metas: list[CallMeta] = []
    iterations = requests = 0
    text = finish_reason = None
    started = time.perf_counter()

    while iterations < config.generation.max_iterations:
        call = await client.complete(conversation, config.generation.temperature, config.tools)
        iterations += 1
        requests += call.requests
        if call.meta is None:
            break  # the request never came back, so there is nothing to continue from
        metas.append(call.meta)
        if not call.tool_calls:
            text, finish_reason = call.text, STOP
            break
        executed = await execute_calls(config.tools, call.tool_calls, iterations)
        invocations.extend(executed)
        conversation.extend(_tool_turns(call, executed))
    else:
        finish_reason = MAX_ITERATIONS

    return AgenticOutcome(
        text=text,
        iterations=iterations,
        tool_calls=invocations,
        metas=metas,
        latency_ms=round((time.perf_counter() - started) * 1000),
        finish_reason=finish_reason,
        requests=requests,
    )


def _tool_turns(call: CallResult, executed: Sequence[ToolInvocation]) -> list[dict[str, Any]]:
    """The assistant tool-call turn followed by one turn per tool result."""
    return [
        call.message,
        *(
            _tool_result(requested, invocation)
            for requested, invocation in zip(call.tool_calls, executed)
        ),
    ]


def _tool_result(call: ToolCall, invocation: ToolInvocation) -> dict[str, Any]:
    """A `tool` turn; completions templates read only its role and content."""
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": invocation.tool,
        "content": invocation.result,
    }

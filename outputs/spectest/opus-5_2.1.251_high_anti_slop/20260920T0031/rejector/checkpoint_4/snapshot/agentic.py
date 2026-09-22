"""The agentic generation scheme: call tools in a loop, then answer.

One loop owns its own conversation. Every response that asks for tools is
appended to it together with the results of those tools and sent back, until
the model answers with text or the iteration limit is reached. Each request
inside the loop is an ordinary paced API call, so loops belonging to different
input rows stay interleaved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from api import ApiClient
from config import TaskConfig
from endpoints import Completion, Endpoint
from templates import Message
from tools import Toolbox, ToolCall

STOP = "stop"
MAX_ITERATIONS = "max_iterations"

#: The per-request fields `meta.iterations_detail` records.
DETAIL_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "finish_reason")


@dataclass(frozen=True)
class Generation:
    """What one generation attempt produced, whether it took one request or many."""

    completion: Completion | None
    #: API requests an agentic loop spent; zero for a task generating in one shot.
    iterations: int = 0
    #: One record per executed tool call, in execution order.
    tool_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AgenticLoop:
    """Runs one tool-calling conversation per generation attempt."""

    client: ApiClient
    endpoint: Endpoint
    toolbox: Toolbox
    task: TaskConfig

    async def run(self, messages: list[Message]) -> Generation:
        """Request, run the tools that were asked for, and repeat until there is an answer."""
        generation = self.task.generation
        conversation = list(messages)
        details: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        started = time.monotonic()

        for iteration in range(1, generation.max_iterations + 1):
            completion = await self.client.complete(
                conversation, self.task.model, generation.temperature, generation.max_tokens, self.toolbox.tools
            )
            if completion is None:
                return Generation(None)

            details.append({key: completion.meta[key] for key in DETAIL_FIELDS})
            if not completion.tool_calls:
                return Generation(Completion(completion.text, _meta(details, started, STOP)), iteration, tuple(records))

            conversation.append(self.endpoint.assistant_message(completion))
            records.extend(await self._call_tools(completion.tool_calls, iteration, conversation))

        return Generation(Completion(None, _meta(details, started, MAX_ITERATIONS)), len(details), tuple(records))

    async def _call_tools(
        self, calls: tuple[ToolCall, ...], iteration: int, conversation: list[Message]
    ) -> list[dict[str, Any]]:
        """Run every tool one response asked for, feeding each result back into the conversation."""
        records = []
        for call in calls:
            result = await self.toolbox.invoke(call)
            records.append({"iteration": iteration, "tool": call.name, "args": call.args, "result": result})
            conversation.append(self.endpoint.tool_message(call, result))
        return records


def build_loop(task: TaskConfig, client: ApiClient, endpoint: Endpoint) -> AgenticLoop | None:
    """A loop for agentic tasks, None for every task that generates in one request."""
    if not task.agentic:
        return None
    return AgenticLoop(client=client, endpoint=endpoint, toolbox=Toolbox(task.tools), task=task)


def _meta(details: list[dict[str, Any]], started: float, finish_reason: str) -> dict[str, Any]:
    """A finished loop's metadata: its totals, its wall-clock time and its per-request detail."""
    return {
        "total_prompt_tokens": sum(detail["prompt_tokens"] for detail in details),
        "total_completion_tokens": sum(detail["completion_tokens"] for detail in details),
        "total_tokens": sum(detail["total_tokens"] for detail in details),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "finish_reason": finish_reason,
        "iterations_detail": details,
    }

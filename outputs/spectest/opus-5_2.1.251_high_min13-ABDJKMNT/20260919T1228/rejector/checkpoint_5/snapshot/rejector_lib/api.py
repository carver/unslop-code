"""Async client for the OpenAI-compatible generation endpoints.

One client serves both `/v1/chat/completions`, which takes a message list and
may answer with `tool_calls`, and `/v1/completions`, which takes a prompt
rendered by a chat template and writes its tool calls into the response text.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import nullcontext
from dataclasses import dataclass

import aiohttp

from .cost import CostRates, CostTracker
from .limits import RateLimiter, Reservation, estimate_prompt_tokens
from .templates import render_prompt
from .tools import (
    ToolCall,
    ToolDefinition,
    message_tool_calls,
    text_tool_calls,
    with_tool_section,
)

MAX_RETRIES = 3
COMPLETIONS = "completions"


@dataclass
class Usage:
    """Running call and token totals, kept per task and for the whole run."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class Endpoint:
    """Where a request goes, which model serves it, and what it is charged to.

    A task's generation and judge calls share one endpoint's `limiter` and
    `usage`, so judge traffic is paced by the same budgets and lands in the
    same per-task totals.
    """

    url: str
    model: str
    max_tokens: int
    limiter: RateLimiter
    usage: Usage
    rates: CostRates
    api_type: str = "chat"
    chat_template: str = "chatml"


@dataclass(frozen=True)
class Completion:
    """One successful generation: its text plus the row metadata it produced.

    `message` is the assistant turn to append when the conversation continues,
    and `tool_calls` are the calls that turn asked for.
    """

    content: str | None
    meta: dict
    message: dict | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class Channel:
    """The API access one task uses: the shared client and its endpoints."""

    client: "ChatClient"
    generation: Endpoint
    judge: Endpoint | None = None


class _TransientError(Exception):
    """A 5xx or connection failure, which is worth retrying."""


class ChatClient:
    """Issues chat completion requests and tallies usage for the summary.

    Each endpoint's limiter decides when a request may go out, and every
    response it reads is priced into the run's cost before the next request is
    allowed to leave.
    """

    def __init__(self, session: aiohttp.ClientSession, cost: CostTracker):
        self._session = session
        self.cost = cost
        self.usage = Usage()
        self.first_request_at: float | None = None
        self.last_response_at: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock time from the first request to the last response."""
        if self.first_request_at is None or self.last_response_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at

    async def complete(
        self,
        messages: list[dict],
        temperature: float,
        endpoint: Endpoint,
        tools: tuple[ToolDefinition, ...] = (),
        hold_slot: bool = True,
    ) -> Completion | None:
        """Run one logical attempt, retrying transient failures.

        `hold_slot` is false for the requests of an agentic loop, which holds
        its concurrency slot itself for as long as the loop runs.
        """
        payload = _payload(messages, temperature, endpoint, tools)
        for _ in range(MAX_RETRIES + 1):
            try:
                return await self._post(payload, endpoint, hold_slot)
            except _TransientError:
                continue
        return None

    async def _post(
        self, payload: dict, endpoint: Endpoint, hold_slot: bool
    ) -> Completion | None:
        """Make a single HTTP call; None means a permanent failure."""
        async with (endpoint.limiter.slots if hold_slot else nullcontext()):
            reserved = _reserved_tokens(payload, endpoint)
            reservation = await endpoint.limiter.reserve(reserved)
            self.cost.ensure_open()
            started = time.monotonic()
            if self.first_request_at is None:
                self.first_request_at = started
            self.usage.calls += 1
            endpoint.usage.calls += 1
            try:
                async with self._session.post(endpoint.url, json=payload) as response:
                    if response.status >= 500:
                        await response.read()
                        raise _TransientError(f"HTTP {response.status}")
                    if response.status != 200:
                        await response.read()
                        return None
                    body = await response.json()
            except aiohttp.ClientError as exc:
                raise _TransientError(str(exc)) from exc
            except asyncio.TimeoutError as exc:
                raise _TransientError("request timed out") from exc
            finally:
                finished = time.monotonic()
                self.last_response_at = finished

        return self._to_completion(
            body, endpoint, reservation, latency_ms=round((finished - started) * 1000)
        )

    def _to_completion(
        self,
        body: dict,
        endpoint: Endpoint,
        reservation: Reservation,
        latency_ms: int,
    ) -> Completion | None:
        """Turn a response body into a Completion, or None if malformed."""
        try:
            choice = body["choices"][0]
            message = _assistant_message(choice, endpoint.api_type)
            content = message["content"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = body.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        for tally in (self.usage, endpoint.usage):
            tally.prompt_tokens += prompt_tokens
            tally.completion_tokens += completion_tokens
        endpoint.limiter.record(reservation, prompt_tokens + completion_tokens)
        self.cost.charge(*endpoint.rates.price(prompt_tokens, completion_tokens))

        return Completion(
            content=content,
            message=message,
            tool_calls=_tool_calls(message, choice, endpoint.api_type),
            meta={
                "model": endpoint.model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "latency_ms": latency_ms,
                "finish_reason": choice.get("finish_reason"),
            },
        )


def _payload(
    messages: list[dict],
    temperature: float,
    endpoint: Endpoint,
    tools: tuple[ToolDefinition, ...],
) -> dict:
    """The request body for one call, in the endpoint's own shape."""
    body = {
        "model": endpoint.model,
        "temperature": temperature,
        "max_tokens": endpoint.max_tokens,
    }
    if endpoint.api_type == COMPLETIONS:
        conversation = with_tool_section(messages, tools) if tools else messages
        return {**body, "prompt": render_prompt(endpoint.chat_template, conversation)}
    if tools:
        body["tools"] = [tool.schema for tool in tools]
    return {**body, "messages": messages}


def _reserved_tokens(payload: dict, endpoint: Endpoint) -> int:
    """What one request claims from the token window before it is sent."""
    return estimate_prompt_tokens(_prompt_texts(payload)) + endpoint.max_tokens


def _prompt_texts(payload: dict) -> list[str]:
    """The text a request carries, in whichever shape its endpoint uses."""
    if "prompt" in payload:
        return [payload["prompt"]]
    return [message.get("content") or "" for message in payload["messages"]]


def _assistant_message(choice: dict, api_type: str) -> dict:
    """The assistant turn a choice describes, as a chat message."""
    if api_type == COMPLETIONS:
        return {"role": "assistant", "content": choice["text"]}
    return choice["message"]


def _tool_calls(message: dict, choice: dict, api_type: str) -> tuple[ToolCall, ...]:
    """The calls the model asked for, read from wherever the shape puts them."""
    if api_type == COMPLETIONS:
        return text_tool_calls(choice["text"])
    return message_tool_calls(message)

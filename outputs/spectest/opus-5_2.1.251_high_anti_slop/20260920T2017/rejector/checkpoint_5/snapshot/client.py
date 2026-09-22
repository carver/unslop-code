"""Rate-limited async client for an OpenAI-compatible generation API.

Two endpoints are supported, chosen per task by `api_type`: `/v1/chat/completions`
takes a messages array and native tool definitions, while `/v1/completions` takes
one prompt string rendered through a chat template. A `Transport` hides that
difference so the rest of the pipeline only ever deals in messages.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

import httpx

from config import NO_COST, TaskConfig
from cost import CostTracker
from limits import RequestLimiter, Reservation, estimate_prompt_tokens
from templates import TEMPLATES, MarkerTemplate, MistralTemplate, parse_tool_calls, with_tools
from tools import ToolCall, ToolConfig

#: Total HTTP attempts per logical call before the call is given up on.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 120.0
CONNECT_TIMEOUT_SECONDS = 10.0
MIN_CONNECTIONS = 8


@dataclass(frozen=True)
class Completion:
    """A successful response: its text, its metadata, and any tools it asked for.

    `text` is None when the model replied with tool calls alone.
    """

    text: str | None
    meta: dict[str, Any]
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass
class ClientStats:
    """Counters for the run summary, accumulated across every HTTP request."""

    api_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    first_request_at: float | None = None
    last_response_at: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock time from the first request to the last response."""
        if self.first_request_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at


class Transport(Protocol):
    """The request body and response shape of one API endpoint."""

    path: str

    def payload(
        self, messages: list[dict[str, Any]], tools: tuple[ToolConfig, ...]
    ) -> dict[str, Any]: ...

    def parse(self, choice: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]: ...


class ChatTransport:
    """`/v1/chat/completions`: a messages array, with tools as their own field."""

    path = "/v1/chat/completions"

    def payload(
        self, messages: list[dict[str, Any]], tools: tuple[ToolConfig, ...]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"messages": messages}
        if tools:
            body["tools"] = [tool.definition for tool in tools]
        return body

    def parse(self, choice: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
        message = choice["message"]
        calls = tuple(
            ToolCall(call["id"], call["function"]["name"], json.loads(call["function"]["arguments"]))
            for call in message.get("tool_calls") or ()
        )
        return message.get("content"), calls


class CompletionsTransport:
    """`/v1/completions`: one rendered prompt, with tools written into it.

    Text responses carry no call ids, so calls are numbered against a
    per-client counter to keep them distinct within a conversation.
    """

    path = "/v1/completions"

    def __init__(self, template: MarkerTemplate | MistralTemplate) -> None:
        self._template = template
        self._responses = itertools.count(1)

    def payload(
        self, messages: list[dict[str, Any]], tools: tuple[ToolConfig, ...]
    ) -> dict[str, Any]:
        return {"prompt": self._template.render(with_tools(messages, tools))}

    def parse(self, choice: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
        text = choice["text"]
        return text, parse_tool_calls(text, f"call_{next(self._responses)}")


class ApiClient:
    """Sends generation requests through one transport, retrying server failures.

    Every request is paced by the task's own `limiter` and charged to the run's
    shared cost tracker. Callers hold a concurrency slot around a whole unit of
    work — `limiter.in_flight()` — while the request and token budgets are
    claimed per request, here.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        task: TaskConfig,
        transport: Transport,
        cost: CostTracker,
    ) -> None:
        self._http = http
        self._url = f"{task.api_url.rstrip('/')}{transport.path}"
        self._model = task.model
        self._rates = task.cost or NO_COST
        self._transport = transport
        self._cost = cost
        self.limiter = RequestLimiter(task.rate_limits)
        self.stats = ClientStats()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        model: str | None = None,
        tools: tuple[ToolConfig, ...] = (),
    ) -> Completion | None:
        """Run one request, or return None if the API never answered.

        A `5xx` or transport failure is retried up to `MAX_ATTEMPTS` times in
        total; every attempt counts as an API call, and claims budget of its own.
        Other error statuses are not retried. `model` overrides the task's model,
        as a judge call may do.

        Raises:
            BudgetExhausted: the run's cost budget ran out before this request
                could be sent.
        """
        model = model or self._model
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self._transport.payload(messages, tools),
        }
        reserved = estimate_prompt_tokens(messages) + max_tokens
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                await asyncio.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            response, latency_ms, reservation = await self._request(payload, reserved)
            if response is None or response.status_code >= 500:
                continue
            if response.is_error:
                return None
            return self._completion(response.json(), latency_ms, model, reservation)
        return None

    async def _request(
        self, payload: dict[str, Any], reserved: int
    ) -> tuple[httpx.Response | None, float, Reservation]:
        """Issue one paced HTTP request, with its latency and token reservation.

        The request waits for its budgets, books `reserved` tokens, and is only
        sent if the run can still afford it — a queued request whose turn comes
        after the budget is spent is dropped rather than sent.
        """
        reservation = await self.limiter.reserve(reserved)
        self._cost.check()
        started = time.monotonic()
        if self.stats.first_request_at is None:
            self.stats.first_request_at = started
        try:
            response = await self._http.post(self._url, json=payload)
        except httpx.RequestError:
            response = None
        finished = time.monotonic()
        self.stats.api_calls += 1
        self.stats.last_response_at = finished
        return response, (finished - started) * 1000, reservation

    def _completion(
        self, body: dict[str, Any], latency_ms: float, model: str, reservation: Reservation
    ) -> Completion:
        """Read one answered request, and charge what it actually used."""
        choice = body["choices"][0]
        usage = body.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        reservation.record(prompt_tokens + completion_tokens)
        self._cost.charge(self._rates, prompt_tokens, completion_tokens)
        self.stats.prompt_tokens += prompt_tokens
        self.stats.completion_tokens += completion_tokens
        meta = {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": usage.get("total_tokens", 0),
            "latency_ms": round(latency_ms),
            "finish_reason": choice.get("finish_reason"),
        }
        text, tool_calls = self._transport.parse(choice)
        return Completion(text=text, meta=meta, tool_calls=tool_calls)


def combine_stats(stats: list[ClientStats]) -> ClientStats:
    """Aggregate per-task counters into one set spanning the whole run."""
    started = [s.first_request_at for s in stats if s.first_request_at is not None]
    finished = [s.last_response_at for s in stats if s.last_response_at is not None]
    return ClientStats(
        api_calls=sum(s.api_calls for s in stats),
        prompt_tokens=sum(s.prompt_tokens for s in stats),
        completion_tokens=sum(s.completion_tokens for s in stats),
        first_request_at=min(started, default=None),
        last_response_at=max(finished, default=None),
    )


@asynccontextmanager
async def open_clients(
    tasks: list[TaskConfig], cost: CostTracker
) -> AsyncIterator[list[ApiClient]]:
    """Open one client per task, in task order.

    Each task paces itself against its own rate limits and may target its own
    server; they share a connection pool sized for their combined budget, so
    tasks running at the same time do not queue behind each other. They share
    the run's `cost` tracker, whose budget stops all of them at once.
    """
    limits = httpx.Limits(max_connections=max(MIN_CONNECTIONS, sum(map(_connections, tasks))))
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as http:
        yield [ApiClient(http, task, _transport(task), cost) for task in tasks]


def _connections(task: TaskConfig) -> int:
    """How many sockets one task can keep busy at once."""
    limits = task.rate_limits
    return limits.max_concurrent or limits.rpm or MIN_CONNECTIONS


def _transport(task: TaskConfig) -> Transport:
    if task.api_type == "completions":
        return CompletionsTransport(TEMPLATES[task.chat_template])
    return ChatTransport()

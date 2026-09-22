"""Rate-limited async client for an OpenAI-compatible chat completions API."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from config import TaskConfig
from prompts import RenderedPrompt

#: Total HTTP attempts per logical call before the call is given up on.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.5
#: How far the rate limiter may run ahead of the paced schedule to fill the pipe.
BURST_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 120.0
CONNECT_TIMEOUT_SECONDS = 10.0
MIN_CONNECTIONS = 8


@dataclass(frozen=True)
class Completion:
    """A successful response: its text plus the metadata recorded per call."""

    text: str
    meta: dict[str, Any]


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


class RateLimiter:
    """Paces request starts at `rpm` per minute, with a burst allowance.

    Each caller reserves the next free slot on a shared schedule, so callers
    queue behind each other instead of all waking for the same instant. The
    schedule may run up to `BURST_SECONDS` ahead of real time, which lets the
    first requests go out together and fill the server's queue; without it the
    pipeline would be drip-fed one request per interval and never reach `rpm`.
    """

    def __init__(self, rpm: int, burst_seconds: float = BURST_SECONDS) -> None:
        self._interval = 60.0 / rpm
        self._burst_seconds = burst_seconds
        self._lock = asyncio.Lock()
        self._next_slot = time.monotonic() - burst_seconds

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = max(self._next_slot, now - self._burst_seconds)
            self._next_slot = slot + self._interval
        delay = slot - now
        if delay > 0:
            await asyncio.sleep(delay)


class ChatClient:
    """Sends chat completion requests, retrying server-side failures."""

    def __init__(self, http: httpx.AsyncClient, api_url: str, model: str, limiter: RateLimiter) -> None:
        self._http = http
        self._url = f"{api_url.rstrip('/')}/v1/chat/completions"
        self._model = model
        self._limiter = limiter
        self.stats = ClientStats()

    async def complete(
        self, prompt: RenderedPrompt, temperature: float, max_tokens: int, model: str | None = None
    ) -> Completion | None:
        """Run one logical generation, or return None if the API never answered.

        A `5xx` or transport failure is retried up to `MAX_ATTEMPTS` times in
        total; every attempt counts as an API call. Other error statuses are not
        retried. `model` overrides the task's model, as a judge call may do.
        """
        model = model or self._model
        payload = {
            "model": model,
            "messages": prompt.messages(),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                await asyncio.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            response, latency_ms = await self._request(payload)
            if response is None or response.status_code >= 500:
                continue
            if response.is_error:
                return None
            return self._completion(response.json(), latency_ms, model)
        return None

    async def _request(self, payload: dict[str, Any]) -> tuple[httpx.Response | None, float]:
        """Issue one paced HTTP request, returning it with its wall-clock latency."""
        await self._limiter.acquire()
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
        return response, (finished - started) * 1000

    def _completion(self, body: dict[str, Any], latency_ms: float, model: str) -> Completion:
        choice = body["choices"][0]
        usage = body.get("usage", {})
        self.stats.prompt_tokens += usage.get("prompt_tokens", 0)
        self.stats.completion_tokens += usage.get("completion_tokens", 0)
        meta = {
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "latency_ms": round(latency_ms),
            "finish_reason": choice.get("finish_reason"),
        }
        return Completion(text=choice["message"]["content"], meta=meta)


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
async def open_clients(tasks: list[TaskConfig]) -> AsyncIterator[list[ChatClient]]:
    """Open one client per task, in task order.

    Each task paces itself against its own `rpm` budget and may target its own
    server; they share a connection pool sized for their combined budget, so
    tasks running at the same time do not queue behind each other.
    """
    limits = httpx.Limits(max_connections=max(MIN_CONNECTIONS, sum(task.rpm for task in tasks)))
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as http:
        yield [
            ChatClient(http, task.api_url, task.model, RateLimiter(task.rpm)) for task in tasks
        ]

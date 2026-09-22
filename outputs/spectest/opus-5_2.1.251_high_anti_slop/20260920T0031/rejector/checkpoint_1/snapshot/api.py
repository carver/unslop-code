"""Async client for an OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

ENDPOINT = "/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 300.0
#: Retries attempted after an initial HTTP 5xx before a row is given up on.
MAX_RETRIES = 3


class RateLimiter:
    """Token bucket pacing request starts to the configured requests-per-minute budget.

    The bucket starts full, so a run may put a full minute of budget in flight
    immediately and then settles to a steady `rpm` requests per minute.
    """

    def __init__(self, rpm: int) -> None:
        self._capacity = float(rpm)
        self._refill_per_second = rpm / 60.0
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._refill_per_second)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                delay = (1.0 - self._tokens) / self._refill_per_second
            await asyncio.sleep(delay)


@dataclass(frozen=True)
class Completion:
    """One successful generation and the metadata recorded for it."""

    text: str
    meta: dict[str, Any]


class ChatClient:
    """Sends chat completion requests, pacing them and retrying server errors.

    Tracks the totals the run summary reports: every HTTP request made
    (retries included) and the span from the first request to the last response.
    """

    def __init__(self, http: httpx.AsyncClient, model: str, limiter: RateLimiter) -> None:
        self._http = http
        self._model = model
        self._limiter = limiter
        self.api_calls = 0
        self._first_request_at: float | None = None
        self._last_response_at = 0.0

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds from the first request sent to the last response received."""
        if self._first_request_at is None:
            return 0.0
        return self._last_response_at - self._first_request_at

    async def complete(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> Completion | None:
        """Generate one completion, or return None once the retry budget is spent."""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for _ in range(MAX_RETRIES + 1):
            response, latency_ms = await self._post(payload)
            if not response.is_server_error:
                response.raise_for_status()
                return _completion(response.json(), self._model, latency_ms)
        return None

    async def _post(self, payload: dict[str, Any]) -> tuple[httpx.Response, int]:
        await self._limiter.acquire()
        self.api_calls += 1
        started = time.monotonic()
        if self._first_request_at is None:
            self._first_request_at = started
        response = await self._http.post(ENDPOINT, json=payload)
        self._last_response_at = time.monotonic()
        return response, round((self._last_response_at - started) * 1000)


def _completion(payload: dict[str, Any], model: str, latency_ms: int) -> Completion:
    choice = payload["choices"][0]
    usage = payload.get("usage", {})
    return Completion(
        text=choice["message"]["content"],
        meta={
            "model": payload.get("model", model),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "latency_ms": latency_ms,
            "finish_reason": choice.get("finish_reason"),
        },
    )

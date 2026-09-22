"""Async client for the OpenAI compatible chat completions endpoint."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import aiohttp

from config import TaskConfig

# One initial request plus two retries, as the API contract allows for 5xx responses.
MAX_HTTP_ATTEMPTS = 3


@dataclass(frozen=True)
class Attempt:
    """One logical generation attempt. `text` is None when the API never answered."""

    text: str | None
    meta: dict | None


class RateLimiter:
    """Token bucket pacing request starts at `rpm` per minute with a one minute burst.

    Waiters queue on the lock, so requests start in the order they were submitted.
    """

    def __init__(self, rpm: int) -> None:
        self._rate = rpm / 60.0
        self._capacity = float(rpm)
        self._tokens = float(rpm)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self._tokens) / self._rate)


class ChatClient:
    """Issues chat completions for one task and counts every HTTP request it makes."""

    def __init__(self, session: aiohttp.ClientSession, config: TaskConfig, limiter: RateLimiter) -> None:
        self._session = session
        self._config = config
        self._limiter = limiter
        self._url = f"{config.api_url}/v1/chat/completions"
        self.api_calls = 0

    async def complete(self, messages: list[dict]) -> Attempt:
        """Request one completion, retrying server errors up to `MAX_HTTP_ATTEMPTS` times."""
        for _ in range(MAX_HTTP_ATTEMPTS):
            await self._limiter.acquire()
            self.api_calls += 1
            attempt = await self._request(messages)
            if attempt is not None:
                return attempt
        return Attempt(None, None)

    async def _request(self, messages: list[dict]) -> Attempt | None:
        """One HTTP round trip. None asks for a retry; an empty Attempt gives up on the row."""
        payload = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.generation.temperature,
            "max_tokens": self._config.generation.max_tokens,
        }
        started = time.monotonic()
        try:
            async with self._session.post(self._url, json=payload) as response:
                if response.status >= 500:
                    return None
                if response.status >= 400:
                    return Attempt(None, None)
                body = await response.json()
        except (aiohttp.ClientError, TimeoutError):
            return None

        return self._to_attempt(body, latency_ms=round((time.monotonic() - started) * 1000))

    def _to_attempt(self, body: dict, latency_ms: int) -> Attempt:
        choice = body["choices"][0]
        usage = body.get("usage", {})
        return Attempt(
            text=choice["message"]["content"],
            meta={
                "model": self._config.model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "latency_ms": latency_ms,
                "finish_reason": choice.get("finish_reason"),
            },
        )

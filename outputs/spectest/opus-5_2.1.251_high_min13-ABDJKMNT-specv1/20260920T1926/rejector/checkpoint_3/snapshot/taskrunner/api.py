"""Async client for the OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import aiohttp

# Total requests spent on one logical call, including retries after 5xx.
MAX_REQUESTS_PER_CALL = 3


@dataclass(frozen=True)
class CallMeta:
    """Metadata for a single completed API call."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    finish_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True)
class CallResult:
    """Outcome of one logical call: the text, its metadata, requests spent."""

    text: str | None
    meta: CallMeta | None
    requests: int


@dataclass
class _Attempt:
    """Outcome of a single HTTP request."""

    retryable: bool
    text: str | None = None
    meta: CallMeta | None = None


@dataclass
class CallWindow:
    """Spans the first request sent to the last response received."""

    first: float | None = field(default=None)
    last: float | None = field(default=None)

    def record(self, start: float, end: float) -> None:
        self.first = start if self.first is None else min(self.first, start)
        self.last = end if self.last is None else max(self.last, end)

    @property
    def elapsed(self) -> float:
        return 0.0 if self.first is None else self.last - self.first


class ChatClient:
    """Issues chat completion requests and retries transient failures."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        model: str,
        max_tokens: int,
        window: CallWindow | None = None,
    ) -> None:
        self._session = session
        self._endpoint = f"{api_url.rstrip('/')}/v1/chat/completions"
        self._model = model
        self._max_tokens = max_tokens
        # Clients that share a window (a task and its judge, or several tasks)
        # report one first-request-to-last-response span for the whole run.
        self.window = window or CallWindow()

    async def complete(
        self, messages: Sequence[dict[str, str]], temperature: float
    ) -> CallResult:
        """Run one logical call, retrying 5xx and transport errors."""
        payload = {
            "model": self._model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }
        requests = 0
        while requests < MAX_REQUESTS_PER_CALL:
            requests += 1
            attempt = await self._request(payload)
            if attempt.text is not None:
                return CallResult(attempt.text, attempt.meta, requests)
            if not attempt.retryable:
                break
        return CallResult(None, None, requests)

    async def _request(self, payload: dict[str, Any]) -> _Attempt:
        """Send one HTTP request, timing it for the run-wide window."""
        started = time.perf_counter()
        try:
            return await self._send(payload, started)
        finally:
            self.window.record(started, time.perf_counter())

    async def _send(self, payload: dict[str, Any], started: float) -> _Attempt:
        try:
            async with self._session.post(self._endpoint, json=payload) as response:
                if response.status >= 500:
                    await response.read()
                    return _Attempt(retryable=True)
                if response.status != 200:
                    await response.read()
                    return _Attempt(retryable=False)
                body = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return _Attempt(retryable=True)

        choice = body["choices"][0]
        usage = body.get("usage") or {}
        meta = CallMeta(
            model=self._model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=round((time.perf_counter() - started) * 1000),
            finish_reason=choice.get("finish_reason"),
        )
        return _Attempt(retryable=False, text=choice["message"]["content"], meta=meta)

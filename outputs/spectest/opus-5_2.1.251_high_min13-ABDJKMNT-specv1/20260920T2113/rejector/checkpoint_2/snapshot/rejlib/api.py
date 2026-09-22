"""HTTP client for the OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Iterable

import httpx

from rejlib.config import TaskConfig
from rejlib.ratelimit import RateLimiter

#: "If a request receives an HTTP 5xx, retry it up to 3 total requests."
MAX_REQUESTS_PER_ATTEMPT = 3


@dataclass
class Stats:
    """Run-wide counters feeding the summary."""

    api_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    first_request: float | None = None
    last_response: float | None = None

    def record_call(self, started: float, finished: float) -> None:
        """Count one HTTP request, including retries and rejection attempts."""
        self.api_calls += 1
        self.extend(started, finished)

    def extend(self, started: float, finished: float) -> None:
        """Widen the measured window so it covers ``[started, finished]``."""
        self.first_request = started if self.first_request is None else min(self.first_request, started)
        self.last_response = finished if self.last_response is None else max(self.last_response, finished)

    @classmethod
    def merged(cls, parts: Iterable["Stats"]) -> "Stats":
        """Run-wide counters over the per-task counters of concurrent tasks."""
        total = cls()
        for part in parts:
            total.api_calls += part.api_calls
            total.prompt_tokens += part.prompt_tokens
            total.completion_tokens += part.completion_tokens
            if part.first_request is not None:
                total.extend(part.first_request, part.last_response)
        return total

    @property
    def elapsed(self) -> float:
        """Wall-clock seconds from the first request to the last response."""
        if self.first_request is None:
            return 0.0
        return max(0.0, self.last_response - self.first_request)


@dataclass
class Attempt:
    """One logical generation attempt: its text (``None`` if it failed) and metadata."""

    content: str | None
    meta: dict


@dataclass
class _Reply:
    """Outcome of a single HTTP request."""

    completion: dict | None
    retryable: bool


class ChatClient:
    """Performs one chat completion per logical attempt, retrying transient failures."""

    def __init__(self, http: httpx.AsyncClient, config: TaskConfig,
                 limiter: RateLimiter, stats: Stats):
        self._http = http
        self._config = config
        self._limiter = limiter
        self._stats = stats

    def variant(self, *, model: str, temperature: float) -> "ChatClient":
        """A client sharing this one's connection, rate budget and counters.

        Used for the judge call of an `llm_judge` task, which addresses its own
        model but competes for the same request budget.
        """
        generation = replace(self._config.generation, temperature=temperature)
        config = replace(self._config, model=model, generation=generation)
        return ChatClient(self._http, config, self._limiter, self._stats)

    async def complete(self, messages: list[dict]) -> Attempt:
        """Send one attempt, retrying 5xx and transport errors up to the request budget."""
        payload = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.generation.temperature,
            "max_tokens": self._config.generation.max_tokens,
        }
        first_started = None
        for request_number in range(1, MAX_REQUESTS_PER_ATTEMPT + 1):
            await self._limiter.acquire()
            started = time.monotonic()
            if first_started is None:
                first_started = started
            reply = await self._send(payload)
            finished = time.monotonic()
            self._stats.record_call(started, finished)

            if reply.completion is not None:
                return self._attempt(reply.completion, finished - started)
            if not reply.retryable or request_number == MAX_REQUESTS_PER_ATTEMPT:
                break
        return Attempt(None, self._meta(latency=time.monotonic() - first_started))

    async def _send(self, payload: dict) -> _Reply:
        try:
            response = await self._http.post(self._config.chat_url, json=payload)
        except httpx.HTTPError:
            return _Reply(None, retryable=True)  # T13: transport failures are transient
        if response.status_code >= 500:
            return _Reply(None, retryable=True)
        if response.status_code >= 400:
            return _Reply(None, retryable=False)
        return _Reply(_parse_completion(response), retryable=False)

    def _attempt(self, completion: dict, latency: float) -> Attempt:
        usage = completion["usage"]
        self._stats.prompt_tokens += usage.get("prompt_tokens", 0)
        self._stats.completion_tokens += usage.get("completion_tokens", 0)
        return Attempt(
            content=completion["content"],
            meta=self._meta(
                latency=latency, usage=usage, finish_reason=completion["finish_reason"]
            ),
        )

    def _meta(self, latency: float, usage: dict | None = None,
              finish_reason: str | None = None) -> dict:
        """The per-attempt metadata object; zeroed token counts for failed attempts (T3)."""
        usage = usage or {}
        return {
            "model": self._config.model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "latency_ms": round(latency * 1000),
            "finish_reason": finish_reason,
        }


def _parse_completion(response: httpx.Response) -> dict | None:
    """Pull message, finish reason and usage out of an OpenAI-style body.

    Returns ``None`` for a 2xx body that is not a usable chat completion; such a
    response is deterministic, so it is not retried.
    """
    try:
        body = response.json()
        choice = body["choices"][0]
        return {
            "content": choice["message"]["content"],
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage") or {},
        }
    except (ValueError, KeyError, IndexError, TypeError):
        return None

"""Async client for an OpenAI-compatible ``/v1/chat/completions`` endpoint."""

import time
from dataclasses import dataclass

import httpx

from ratelimit import RateLimiter
from results import CallMeta

#: Total HTTP requests spent on one logical attempt, including retries of server errors.
MAX_HTTP_ATTEMPTS = 3


@dataclass
class CallStats:
    """HTTP-level counters shared by every call a client makes."""

    api_calls: int = 0
    first_request_at: float | None = None
    last_response_at: float | None = None

    def record(self, started_at: float, finished_at: float) -> None:
        """Count one HTTP request and widen the observed first-request/last-response window."""
        self.api_calls += 1
        self._widen(started_at, finished_at)

    def merge(self, other: "CallStats") -> None:
        """Fold another task's counters and timing window into this one."""
        self.api_calls += other.api_calls
        if other.first_request_at is not None:
            self._widen(other.first_request_at, other.last_response_at)

    def _widen(self, started_at: float, finished_at: float) -> None:
        if self.first_request_at is None:
            self.first_request_at = started_at
            self.last_response_at = finished_at
            return
        self.first_request_at = min(self.first_request_at, started_at)
        self.last_response_at = max(self.last_response_at, finished_at)

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds from the first request to the last response."""
        if self.first_request_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at


@dataclass(frozen=True)
class Completion:
    """One logical attempt: the response text (``None`` when it failed) and its metadata."""

    text: str | None
    meta: CallMeta


class ChatClient:
    """Issues rate-limited chat completion requests, retrying server errors."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: RateLimiter,
        api_url: str,
        model: str,
        stats: CallStats,
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._endpoint = f"{api_url}/v1/chat/completions"
        self._model = model
        self._stats = stats

    async def complete(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> Completion:
        """Request one completion, retrying up to ``MAX_HTTP_ATTEMPTS`` times on 5xx responses."""
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        error = "no response"
        latency_ms = 0
        for _ in range(MAX_HTTP_ATTEMPTS):
            await self._limiter.acquire()
            started = time.monotonic()
            try:
                response = await self._http.post(self._endpoint, json=body)
            except httpx.HTTPError as exc:
                response, error = None, f"request failed: {exc}"
            finished = time.monotonic()
            self._stats.record(started, finished)
            latency_ms = round((finished - started) * 1000)

            if response is None:
                continue
            if response.is_server_error:
                error = f"server returned HTTP {response.status_code}"
                continue
            if response.is_error:
                return self._failure(f"server returned HTTP {response.status_code}", latency_ms)
            return self._success(response.json(), latency_ms)
        return self._failure(error, latency_ms)

    def _success(self, payload: dict, latency_ms: int) -> Completion:
        choice = payload["choices"][0]
        usage = payload.get("usage") or {}
        meta = CallMeta(
            model=self._model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
        )
        return Completion(text=choice["message"]["content"], meta=meta)

    def _failure(self, error: str, latency_ms: int) -> Completion:
        """Metadata for an attempt that never produced a usable response."""
        meta = CallMeta(
            model=self._model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=latency_ms,
            finish_reason=None,
            error=error,
        )
        return Completion(text=None, meta=meta)

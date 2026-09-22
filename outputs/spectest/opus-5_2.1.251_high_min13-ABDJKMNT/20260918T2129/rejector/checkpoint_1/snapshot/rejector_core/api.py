"""Chat completions client: request shaping, retries, and call accounting."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from .config import TaskConfig

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.1
REQUEST_TIMEOUT_SECONDS = 120.0


@dataclass
class Completion:
    """One successful completion plus the metadata reported for it."""

    text: str
    meta: dict


@dataclass
class ApiStats:
    """Counters spanning every HTTP request the run makes."""

    calls: int = 0
    first_request_at: float | None = None
    last_response_at: float | None = None

    def record_request(self) -> None:
        self.calls += 1
        if self.first_request_at is None:
            self.first_request_at = time.perf_counter()

    def record_response(self) -> None:
        self.last_response_at = time.perf_counter()

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds from the first request to the last response."""
        if self.first_request_at is None or self.last_response_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at


class _Retryable(Exception):
    """A failure worth retrying: an HTTP 5xx or a transport error."""


class ChatClient:
    """Sends one chat completion request at a time, retrying server errors."""

    def __init__(self, http: httpx.AsyncClient, task: TaskConfig):
        self._http = http
        self._task = task
        self.stats = ApiStats()

    async def complete(self, messages: list[dict]) -> Completion | None:
        """Return the completion, or None once the retry budget is spent."""
        payload = {
            "model": self._task.model,
            "messages": messages,
            "temperature": self._task.generation.temperature,
            "max_tokens": self._task.generation.max_tokens,
        }
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._post(payload)
            except _Retryable:
                if attempt == MAX_RETRIES:
                    break
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
        return None

    async def _post(self, payload: dict) -> Completion | None:
        """One HTTP call. Returns None for failures that must not be retried."""
        self.stats.record_request()
        started = time.perf_counter()
        try:
            response = await self._http.post(self._task.completions_url, json=payload)
        except httpx.HTTPError as exc:
            self.stats.record_response()
            raise _Retryable(str(exc)) from exc

        self.stats.record_response()
        if response.status_code >= 500:
            raise _Retryable(f"server returned {response.status_code}")
        if response.status_code >= 400:
            return None

        latency_ms = round((time.perf_counter() - started) * 1000)
        return self._to_completion(response.json(), latency_ms)

    def _to_completion(self, data: dict, latency_ms: int) -> Completion:
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return Completion(
            text=choice["message"]["content"],
            meta={
                "model": self._task.model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "latency_ms": latency_ms,
                "finish_reason": choice.get("finish_reason"),
            },
        )

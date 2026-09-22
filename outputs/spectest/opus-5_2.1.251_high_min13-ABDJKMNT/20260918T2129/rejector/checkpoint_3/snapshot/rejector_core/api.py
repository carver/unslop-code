"""Chat completions client: request shaping, retries, and call accounting."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

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
class RunStats:
    """Counters spanning every HTTP request the run makes, task by task.

    Generation and judge calls are both recorded here, so `calls` is the
    summary's `total_api_calls` and `by_task` its per-task equivalent.
    """

    calls: int = 0
    by_task: dict[str | None, int] = field(default_factory=dict)
    first_request_at: float | None = None
    last_response_at: float | None = None

    def record_request(self, task_name: str | None) -> None:
        self.calls += 1
        self.by_task[task_name] = self.by_task.get(task_name, 0) + 1
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
    """Sends chat completion requests for one task, retrying server errors."""

    def __init__(self, http: httpx.AsyncClient, task: TaskConfig, stats: RunStats):
        self._http = http
        self._task = task
        self._stats = stats

    async def complete(self, messages: list[dict], model: str | None = None) -> Completion | None:
        """Return the completion, or None once the retry budget is spent."""
        payload = {
            "model": model or self._task.model,
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
        self._stats.record_request(self._task.name)
        started = time.perf_counter()
        try:
            response = await self._http.post(self._task.completions_url, json=payload)
        except httpx.HTTPError as exc:
            self._stats.record_response()
            raise _Retryable(str(exc)) from exc

        self._stats.record_response()
        if response.status_code >= 500:
            raise _Retryable(f"server returned {response.status_code}")
        if response.status_code >= 400:
            return None

        latency_ms = round((time.perf_counter() - started) * 1000)
        return self._to_completion(response.json(), payload["model"], latency_ms)

    @staticmethod
    def _to_completion(data: dict, model: str, latency_ms: int) -> Completion:
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return Completion(
            text=choice["message"]["content"],
            meta={
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "latency_ms": latency_ms,
                "finish_reason": choice.get("finish_reason"),
            },
        )

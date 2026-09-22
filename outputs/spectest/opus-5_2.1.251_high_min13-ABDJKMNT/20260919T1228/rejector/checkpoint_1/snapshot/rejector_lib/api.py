"""Async client for the OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import aiohttp

MAX_RETRIES = 3


@dataclass(frozen=True)
class Completion:
    """One successful generation: its text plus the row metadata it produced."""

    content: str
    meta: dict


class _TransientError(Exception):
    """A 5xx or connection failure, which is worth retrying."""


class ChatClient:
    """Issues chat completion requests and tallies usage for the summary.

    At most `concurrency` requests are in flight at once; the server queues the
    rest, so the cap is what keeps its capacity busy without unbounded fan-out.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        api_url: str,
        model: str,
        max_tokens: int,
        concurrency: int,
    ):
        self._session = session
        self._url = f"{api_url}/v1/chat/completions"
        self._model = model
        self._max_tokens = max_tokens
        self._slots = asyncio.Semaphore(concurrency)
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.first_request_at: float | None = None
        self.last_response_at: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock time from the first request to the last response."""
        if self.first_request_at is None or self.last_response_at is None:
            return 0.0
        return self.last_response_at - self.first_request_at

    async def complete(self, messages: list[dict], temperature: float) -> Completion | None:
        """Run one logical attempt, retrying transient failures."""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }
        for _ in range(MAX_RETRIES + 1):
            try:
                return await self._post(payload)
            except _TransientError:
                continue
        return None

    async def _post(self, payload: dict) -> Completion | None:
        """Make a single HTTP call; None means a permanent failure."""
        async with self._slots:
            started = time.monotonic()
            if self.first_request_at is None:
                self.first_request_at = started
            self.total_calls += 1
            try:
                async with self._session.post(self._url, json=payload) as response:
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

        return self._to_completion(body, latency_ms=round((finished - started) * 1000))

    def _to_completion(self, body: dict, latency_ms: int) -> Completion | None:
        """Turn a chat completions body into a Completion, or None if malformed."""
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = body.get("usage") or {}
        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.total_completion_tokens += usage.get("completion_tokens", 0)
        return Completion(
            content=content,
            meta={
                "model": self._model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "latency_ms": latency_ms,
                "finish_reason": choice.get("finish_reason"),
            },
        )

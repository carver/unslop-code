"""HTTP client for the OpenAI-compatible generation endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Iterable

import httpx

from rejlib.config import TaskConfig
from rejlib.scheduler import Scheduler
from rejlib.templates import render_prompt
from rejlib.tokens import estimate_tokens, payload_words
from rejlib.tools import ToolSpec, definitions

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
    """One logical generation attempt: the assistant turn it returned, and metadata.

    ``message`` is ``None`` when every request of the attempt failed.
    """

    message: dict | None
    meta: dict

    @property
    def content(self) -> str | None:
        """The assistant text; ``None`` for a reply that only asks for tools."""
        return None if self.message is None else self.message.get("content")


@dataclass
class _Reply:
    """Outcome of a single HTTP request."""

    completion: dict | None
    retryable: bool


class ApiClient:
    """Performs one API request per logical attempt, retrying transient failures.

    The task's ``api_type`` decides whether that is a chat completion carrying a
    `messages` array or a text completion carrying a rendered prompt.
    """

    def __init__(self, http: httpx.AsyncClient, config: TaskConfig,
                 scheduler: Scheduler, stats: Stats):
        self._http = http
        self._config = config
        self._scheduler = scheduler
        self._stats = stats

    @property
    def scheduler(self) -> Scheduler:
        """The task's scheduler, which an agentic loop holds a slot from."""
        return self._scheduler

    def variant(self, *, model: str, temperature: float) -> "ApiClient":
        """A client sharing this one's connection, rate budget and counters.

        Used for the judge call of an `llm_judge` task, which addresses its own
        model but competes for the same request budget.
        """
        generation = replace(self._config.generation, temperature=temperature)
        config = replace(self._config, model=model, generation=generation)
        return ApiClient(self._http, config, self._scheduler, self._stats)

    async def complete(self, messages: list[dict],
                       tools: tuple[ToolSpec, ...] = ()) -> Attempt:
        """Send one attempt, retrying 5xx and transport errors up to the request budget.

        Every request of the attempt reserves its own rate and token budget, and
        settles it against the usage the reply reports.
        """
        payload = request_payload(self._config, messages, tools)
        reserved = self._reservation(payload)
        first_started = None
        for request_number in range(1, MAX_REQUESTS_PER_ATTEMPT + 1):
            async with self._scheduler.request(reserved) as pending:
                started = time.monotonic()
                if first_started is None:
                    first_started = started
                reply = await self._send(payload)
                finished = time.monotonic()
                self._stats.record_call(started, finished)

                if reply.completion is not None:
                    pending.settle(reply.completion["usage"])
                    return self._attempt(reply.completion, finished - started)
                if not reply.retryable or request_number == MAX_REQUESTS_PER_ATTEMPT:
                    break
        return Attempt(None, self._meta(latency=time.monotonic() - first_started))

    def _reservation(self, payload: dict) -> int:
        """The token budget to hold before dispatch: the prompt estimate plus
        everything the reply is allowed to generate."""
        return (estimate_tokens(payload_words(payload))
                + self._config.generation.max_tokens)

    async def _send(self, payload: dict) -> _Reply:
        try:
            response = await self._http.post(self._config.request_url, json=payload)
        except httpx.HTTPError:
            return _Reply(None, retryable=True)  # T13: transport failures are transient
        if response.status_code >= 500:
            return _Reply(None, retryable=True)
        if response.status_code >= 400:
            return _Reply(None, retryable=False)
        return _Reply(_parse_completion(response, self._config.api_type), retryable=False)

    def _attempt(self, completion: dict, latency: float) -> Attempt:
        usage = completion["usage"]
        self._stats.prompt_tokens += usage.get("prompt_tokens", 0)
        self._stats.completion_tokens += usage.get("completion_tokens", 0)
        return Attempt(
            message=completion["message"],
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


def request_payload(config: TaskConfig, messages: list[dict],
                   tools: tuple[ToolSpec, ...] = ()) -> dict:
    """The request body: the shared sampling parameters plus the mode's own fields."""
    generation = config.generation
    return {
        "model": config.model,
        "temperature": generation.temperature,
        "max_tokens": generation.max_tokens,
        **_BODIES[config.api_type](config, messages, tools),
    }


def _chat_body(config: TaskConfig, messages: list[dict],
               tools: tuple[ToolSpec, ...]) -> dict:
    """Chat mode carries the conversation, plus the task's tool definitions."""
    if not tools:
        return {"messages": messages}
    return {"messages": messages, "tools": definitions(tools)}


def _completions_body(config: TaskConfig, messages: list[dict],
                      tools: tuple[ToolSpec, ...]) -> dict:
    """Completions mode carries the conversation as one templated string."""
    return {"prompt": render_prompt(config.chat_template, messages)}


_BODIES = {"chat": _chat_body, "completions": _completions_body}

#: "completions responses return `choices[].text`, not `choices[].message`"
_ASSISTANT_TURN = {
    "chat": lambda choice: dict(choice["message"]),
    "completions": lambda choice: {"role": "assistant", "content": choice["text"]},
}


def _parse_completion(response: httpx.Response, api_type: str) -> dict | None:
    """Pull the assistant turn, finish reason and usage out of an OpenAI-style body.

    Returns ``None`` for a 2xx body that is not a usable completion; such a
    response is deterministic, so it is not retried.
    """
    try:
        body = response.json()
        choice = body["choices"][0]
        return {
            "message": _ASSISTANT_TURN[api_type](choice),
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage") or {},
        }
    except (ValueError, KeyError, IndexError, TypeError):
        return None

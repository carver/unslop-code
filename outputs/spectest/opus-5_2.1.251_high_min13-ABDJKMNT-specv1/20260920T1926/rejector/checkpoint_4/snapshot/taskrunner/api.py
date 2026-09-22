"""Async clients for the OpenAI-compatible chat and completions endpoints.

Both flavours share the retry loop and the timing window; they differ only in
the payload they send and the choice shape they read back, so each subclass
supplies those two pieces.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import aiohttp

from .templates import parse_tool_calls, render_prompt, with_tool_instructions
from .tools import ToolCall, ToolConfig

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
        return {"model": self.model, **self.usage()}

    def usage(self) -> dict[str, Any]:
        """What the call cost, without naming the model that served it.

        This is the per-iteration shape of an agentic row's
        `meta.iterations_detail`.
        """
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True)
class CallResult:
    """Outcome of one logical call: the reply, its metadata, requests spent.

    `message` is the assistant turn to append when the conversation
    continues, and `tool_calls` the invocations it asked for.
    """

    text: str | None
    meta: CallMeta | None
    requests: int
    tool_calls: tuple[ToolCall, ...] = ()
    message: dict[str, Any] | None = None


@dataclass
class _Attempt:
    """Outcome of a single HTTP request."""

    retryable: bool
    answered: bool = False
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    meta: CallMeta | None = None
    message: dict[str, Any] | None = None


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


class ModelClient:
    """Issues completion requests and retries transient failures."""

    path = ""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        model: str,
        max_tokens: int,
        window: CallWindow | None = None,
    ) -> None:
        self._session = session
        self._endpoint = f"{api_url.rstrip('/')}{self.path}"
        self._model = model
        self._max_tokens = max_tokens
        # Clients that share a window (a task and its judge, or several tasks)
        # report one first-request-to-last-response span for the whole run.
        self.window = window or CallWindow()

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        temperature: float,
        tools: Sequence[ToolConfig] = (),
    ) -> CallResult:
        """Run one logical call, retrying 5xx and transport errors."""
        payload = self._payload(messages, temperature, tools)
        requests = 0
        while requests < MAX_REQUESTS_PER_CALL:
            requests += 1
            attempt = await self._request(payload)
            if attempt.answered:
                return CallResult(
                    attempt.text, attempt.meta, requests, attempt.tool_calls, attempt.message
                )
            if not attempt.retryable:
                break
        return CallResult(None, None, requests)

    def _payload(
        self,
        messages: Sequence[Mapping[str, Any]],
        temperature: float,
        tools: Sequence[ToolConfig],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _read(self, choice: Mapping[str, Any]) -> _Attempt:
        raise NotImplementedError

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
        attempt = self._read(choice)
        attempt.meta = self._meta(body, choice, started)
        return attempt

    def _meta(
        self, body: Mapping[str, Any], choice: Mapping[str, Any], started: float
    ) -> CallMeta:
        usage = body.get("usage") or {}
        return CallMeta(
            model=self._model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=round((time.perf_counter() - started) * 1000),
            finish_reason=choice.get("finish_reason"),
        )


class ChatClient(ModelClient):
    """`/v1/chat/completions`: a messages array and native tool calls."""

    path = "/v1/chat/completions"

    def _payload(self, messages, temperature, tools):
        payload = {
            "model": self._model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload["tools"] = [tool.as_request_tool() for tool in tools]
        return payload

    def _read(self, choice):
        message = choice["message"]
        return _Attempt(
            retryable=False,
            answered=True,
            text=message.get("content"),
            tool_calls=_chat_tool_calls(message),
            message=dict(message),
        )


class CompletionsClient(ModelClient):
    """`/v1/completions`: a templated prompt string and `<tool_call>` text."""

    path = "/v1/completions"

    def __init__(self, session, api_url, model, max_tokens, template, window=None) -> None:
        super().__init__(session, api_url, model, max_tokens, window)
        self._template = template

    def _payload(self, messages, temperature, tools):
        return {
            "model": self._model,
            "prompt": render_prompt(self._template, with_tool_instructions(messages, tools)),
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }

    def _read(self, choice):
        text = choice["text"]
        return _Attempt(
            retryable=False,
            answered=True,
            text=text,
            tool_calls=parse_tool_calls(text),
            message={"role": "assistant", "content": text},
        )


def _chat_tool_calls(message: Mapping[str, Any]) -> tuple[ToolCall, ...]:
    """Read the OpenAI `tool_calls` array, parsing each argument string."""
    return tuple(
        ToolCall(
            id=call.get("id"),
            name=call["function"]["name"],
            arguments=_arguments(call["function"].get("arguments")),
        )
        for call in message.get("tool_calls") or ()
    )


def _arguments(raw: str | None) -> dict[str, Any]:
    """`function.arguments` is a JSON string; an unparsable one means none."""
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}

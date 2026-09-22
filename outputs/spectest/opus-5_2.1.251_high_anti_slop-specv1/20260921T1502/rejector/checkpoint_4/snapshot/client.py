"""Async clients for the OpenAI compatible chat completions and completions endpoints.

Both speak the same conversation of messages; the client for the configured
`api_type` decides how that conversation reaches the server, how a response is
read back, and how a tool exchange is written into it.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Sequence

import aiohttp

from config import TaskConfig
from templates import TEMPLATES, parse_tool_calls
from tools import Tool, ToolCall, parse_arguments

# One initial request plus two retries, as the API contract allows for 5xx responses.
MAX_HTTP_ATTEMPTS = 3


@dataclass(frozen=True)
class Attempt:
    """One logical generation attempt. `text` is None when the API never answered."""

    text: str | None
    meta: dict | None
    tool_calls: tuple[ToolCall, ...] = ()


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


class ApiClient:
    """Issues completions for one task and counts every HTTP request it makes.

    Subclasses own one endpoint: the part of the payload carrying the
    conversation, the part of a choice carrying the answer, and the turns a tool
    exchange adds back to the conversation.
    """

    path = ""

    def __init__(self, session: aiohttp.ClientSession, config: TaskConfig, limiter: RateLimiter) -> None:
        self._session = session
        self._config = config
        self._limiter = limiter
        self._url = f"{config.api_url}{self.path}"
        self.api_calls = 0

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
        tools: Sequence[Tool] = (),
    ) -> Attempt:
        """Request one completion, retrying server errors up to `MAX_HTTP_ATTEMPTS` times.

        `model` and `temperature` default to the task's; judge calls override them.
        `tools` are the tools an agentic loop offers the model for this request.
        """
        model = model or self._config.model
        if temperature is None:
            temperature = self._config.generation.temperature
        for _ in range(MAX_HTTP_ATTEMPTS):
            await self._limiter.acquire()
            self.api_calls += 1
            attempt = await self._request(messages, model, temperature, tools)
            if attempt is not None:
                return attempt
        return Attempt(None, None)

    async def _request(
        self, messages: list[dict], model: str, temperature: float, tools: Sequence[Tool]
    ) -> Attempt | None:
        """One HTTP round trip. None asks for a retry; an empty Attempt gives up on the row."""
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": self._config.generation.max_tokens,
            **self._conversation(messages, tools),
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

        return self._attempt(body, model, latency_ms=round((time.monotonic() - started) * 1000))

    def _attempt(self, body: dict, model: str, latency_ms: int) -> Attempt:
        """Shape one API response into an attempt and its metadata."""
        choice = body["choices"][0]
        usage = body.get("usage", {})
        text, tool_calls = self._answer(choice)
        return Attempt(
            text=text,
            meta={
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "latency_ms": latency_ms,
                "finish_reason": choice.get("finish_reason"),
            },
            tool_calls=tool_calls,
        )


class ChatClient(ApiClient):
    """`/v1/chat/completions`: messages in, an assistant message out."""

    path = "/v1/chat/completions"

    def _conversation(self, messages: list[dict], tools: Sequence[Tool]) -> dict:
        if not tools:
            return {"messages": messages}
        return {"messages": messages, "tools": [tool.definition for tool in tools]}

    def _answer(self, choice: dict) -> tuple[str | None, tuple[ToolCall, ...]]:
        message = choice["message"]
        calls = tuple(
            ToolCall(
                name=call["function"]["name"],
                arguments=parse_arguments(call["function"]["arguments"]),
                id=call.get("id"),
            )
            for call in message.get("tool_calls") or ()
        )
        return message.get("content"), calls

    def assistant_turn(self, attempt: Attempt) -> dict:
        """The assistant's tool call message, as the endpoint expects it echoed back."""
        return {
            "role": "assistant",
            "content": attempt.text,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in attempt.tool_calls
            ],
        }

    def tool_turns(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        """One tool message per result, tied to the call it answers."""
        return [
            {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result}
            for call, result in results
        ]


class CompletionsClient(ApiClient):
    """`/v1/completions`: a template rendered prompt in, plain text out.

    The endpoint has no tool support of its own, so the tools are described in
    the prompt and calls are parsed back out of the response text.
    """

    path = "/v1/completions"

    def __init__(self, session: aiohttp.ClientSession, config: TaskConfig, limiter: RateLimiter) -> None:
        super().__init__(session, config, limiter)
        self._template = TEMPLATES[config.chat_template]

    def _conversation(self, messages: list[dict], tools: Sequence[Tool]) -> dict:
        return {"prompt": self._template.render(messages, tools)}

    def _answer(self, choice: dict) -> tuple[str | None, tuple[ToolCall, ...]]:
        text = choice["text"]
        return text, parse_tool_calls(text)

    def assistant_turn(self, attempt: Attempt) -> dict:
        """The reply verbatim: its tool call blocks are part of the conversation."""
        return {"role": "assistant", "content": attempt.text}

    def tool_turns(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        return [{"role": "tool", "name": call.name, "content": result} for call, result in results]


_CLIENTS = {"chat": ChatClient, "completions": CompletionsClient}


def client_for(
    session: aiohttp.ClientSession, config: TaskConfig, limiter: RateLimiter
) -> ApiClient:
    """The client for the task's `api_type`."""
    return _CLIENTS[config.api_type](session, config, limiter)


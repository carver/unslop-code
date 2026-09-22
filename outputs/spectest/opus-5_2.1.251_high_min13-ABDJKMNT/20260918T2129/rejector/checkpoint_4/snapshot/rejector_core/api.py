"""Model client: request shaping for both API types, retries, and accounting."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx

from .chat_templates import render_prompt
from .config import TaskConfig
from .tools import ToolSpec

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.1
REQUEST_TIMEOUT_SECONDS = 120.0

# The text form a completions-mode model uses to request a tool.
TOOL_CALL_BLOCK = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


@dataclass(frozen=True)
class ToolInvocation:
    """One tool the model asked for, with its arguments already parsed."""

    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    """One successful response: its text, its tool calls, and its metadata.

    `message` is the assistant turn to append when the conversation
    continues; `text` is None whenever the model called tools instead of
    answering.
    """

    text: str | None
    meta: dict
    message: dict
    tool_calls: tuple[ToolInvocation, ...] = ()


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


class ModelClient:
    """Sends generation requests for one task, retrying server errors.

    The task's `api_type` decides both the endpoint and the wire format: a
    chat request carries the conversation as messages, a completions request
    carries it as a prompt rendered with the task's chat template.
    """

    def __init__(self, http: httpx.AsyncClient, task: TaskConfig, stats: RunStats):
        self._http = http
        self._task = task
        self._stats = stats

    async def complete(
        self, messages: list[dict], model: str | None = None, tools: Sequence[ToolSpec] = ()
    ) -> Completion | None:
        """Return the completion, or None once the retry budget is spent."""
        payload = self._payload(messages, model or self._task.model, tools)
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._post(payload)
            except _Retryable:
                if attempt == MAX_RETRIES:
                    break
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
        return None

    def _payload(self, messages: list[dict], model: str, tools: Sequence[ToolSpec]) -> dict:
        payload = {
            "model": model,
            "temperature": self._task.generation.temperature,
            "max_tokens": self._task.generation.max_tokens,
        }
        if self._completions_mode:
            payload["prompt"] = render_prompt(self._task.chat_template, messages, tools)
            return payload

        payload["messages"] = messages
        if tools:
            payload["tools"] = [tool.definition for tool in tools]
        return payload

    async def _post(self, payload: dict) -> Completion | None:
        """One HTTP call. Returns None for failures that must not be retried."""
        self._stats.record_request(self._task.name)
        started = time.perf_counter()
        try:
            response = await self._http.post(self._task.request_url, json=payload)
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

    def _to_completion(self, data: dict, model: str, latency_ms: int) -> Completion:
        choice = data["choices"][0]
        usage = data.get("usage", {})
        meta = {
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "latency_ms": latency_ms,
            "finish_reason": choice.get("finish_reason"),
        }
        if self._completions_mode:
            return _from_text(choice["text"], meta)
        return _from_message(choice["message"], meta)

    @property
    def _completions_mode(self) -> bool:
        return self._task.api_type == "completions"


def _from_message(message: dict, meta: dict) -> Completion:
    """Read a chat response, whose tool calls are a structured field."""
    calls = tuple(
        ToolInvocation(call["id"], call["function"]["name"], _decode(call["function"]["arguments"]))
        for call in message.get("tool_calls") or ()
    )
    return Completion(text=message.get("content"), meta=meta, message=message, tool_calls=calls)


def _from_text(text: str, meta: dict) -> Completion:
    """Read a completions response, whose tool calls are text blocks."""
    blocks = [_decode(match) for match in TOOL_CALL_BLOCK.findall(text)]
    calls = tuple(
        ToolInvocation(f"call_{index}", block["name"], _decode(block.get("arguments")))
        for index, block in enumerate(blocks, start=1)
        if "name" in block
    )
    return Completion(
        text=None if calls else text,
        meta=meta,
        message={"role": "assistant", "content": text},
        tool_calls=calls,
    )


def _decode(raw) -> dict:
    """A JSON object the model produced, empty when it is absent or malformed.

    Chat responses send tool arguments as a JSON string and completions-mode
    responses embed whole objects in text, so both are parsed here.
    """
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}

"""Async clients for OpenAI-compatible ``/v1/chat/completions`` and ``/v1/completions``."""

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from chat_templates import Messages, render_prompt
from ratelimit import RateLimiter
from results import CallMeta
from tools import ToolConfig, tool_definitions, tool_instructions

#: Total HTTP requests spent on one logical attempt, including retries of server errors.
MAX_HTTP_ATTEMPTS = 3
#: How a completions-mode model writes a tool call, having no native tool_calls field.
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


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
class ToolCall:
    """One tool invocation the model asked for, with its arguments already parsed."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Completion:
    """One logical attempt and its metadata.

    ``text`` is ``None`` when the call failed or when the model asked for tools
    instead of answering, in which case ``tool_calls`` holds what it asked for.
    """

    text: str | None
    meta: CallMeta
    tool_calls: tuple[ToolCall, ...] = ()


class ModelClient:
    """Issues rate-limited generation requests to one endpoint, retrying server errors.

    Subclasses own the request body, how a choice is read back, and the shape of
    the messages an agentic loop appends between requests.
    """

    #: Path appended to the API base url.
    path = ""

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
        self._endpoint = f"{api_url}{self.path}"
        self._model = model
        self._stats = stats

    async def complete(
        self,
        messages: Messages,
        temperature: float,
        max_tokens: int,
        tools: tuple[ToolConfig, ...] = (),
    ) -> Completion:
        """Request one completion, retrying up to ``MAX_HTTP_ATTEMPTS`` times on 5xx responses."""
        body = {
            "model": self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self._payload(messages, tools),
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

    def _payload(self, messages: Messages, tools: tuple[ToolConfig, ...]) -> dict[str, Any]:
        """The request fields that carry the conversation and the tools it may use."""
        raise NotImplementedError

    def _read(self, choice: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
        """Split one response choice into its final text and the tool calls it requested."""
        raise NotImplementedError

    def assistant_tool_message(self, calls: tuple[ToolCall, ...]) -> dict[str, Any]:
        """The assistant turn recording ``calls``, appended before their results."""
        raise NotImplementedError

    def tool_result_message(self, call: ToolCall, result: str) -> dict[str, Any]:
        """The turn handing one tool's result back to the model."""
        raise NotImplementedError

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
        text, tool_calls = self._read(choice)
        return Completion(text=text, meta=meta, tool_calls=tool_calls)

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


class ChatClient(ModelClient):
    """Talks to ``/v1/chat/completions``, where tools are a native request field."""

    path = "/v1/chat/completions"

    def _payload(self, messages: Messages, tools: tuple[ToolConfig, ...]) -> dict[str, Any]:
        payload: dict[str, Any] = {"messages": messages}
        if tools:
            payload["tools"] = tool_definitions(tools)
        return payload

    def _read(self, choice: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
        message = choice["message"]
        calls = tuple(
            ToolCall(call["id"], call["function"]["name"], json.loads(call["function"]["arguments"]))
            for call in message.get("tool_calls") or ()
        )
        return message.get("content"), calls

    def assistant_tool_message(self, calls: tuple[ToolCall, ...]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.args)},
                }
                for call in calls
            ],
        }

    def tool_result_message(self, call: ToolCall, result: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": result}


class CompletionsClient(ModelClient):
    """Talks to ``/v1/completions``, rendering the conversation with a chat template.

    Tool definitions, tool calls, and tool results all live in the prompt text,
    since the endpoint knows nothing about either messages or tools.
    """

    path = "/v1/completions"

    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: RateLimiter,
        api_url: str,
        model: str,
        stats: CallStats,
        template: str,
    ) -> None:
        super().__init__(http, limiter, api_url, model, stats)
        self._template = template

    def _payload(self, messages: Messages, tools: tuple[ToolConfig, ...]) -> dict[str, Any]:
        return {"prompt": render_prompt(self._template, _with_tool_instructions(messages, tools))}

    def _read(self, choice: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
        text = choice["text"]
        calls = tuple(
            _parsed_call(index, block)
            for index, block in enumerate(TOOL_CALL_RE.findall(text or ""))
        )
        return (None if calls else text), calls

    def assistant_tool_message(self, calls: tuple[ToolCall, ...]) -> dict[str, Any]:
        blocks = "\n".join(
            "<tool_call>\n" + json.dumps({"name": call.name, "arguments": call.args}) + "\n</tool_call>"
            for call in calls
        )
        return {"role": "assistant", "content": blocks}

    def tool_result_message(self, call: ToolCall, result: str) -> dict[str, Any]:
        return {"role": "tool", "content": f"<tool_response>\n{result}\n</tool_response>"}


def _parsed_call(index: int, block: str) -> ToolCall:
    """Read one ``<tool_call>`` block, whose arguments are already a JSON object."""
    payload = json.loads(block)
    return ToolCall(f"call_{index}", payload["name"], payload.get("arguments") or {})


def _with_tool_instructions(messages: Messages, tools: tuple[ToolConfig, ...]) -> Messages:
    """Fold the tool definitions into the system turn, adding one if the task has none."""
    if not tools:
        return messages
    instructions = tool_instructions(tools)
    if messages and messages[0]["role"] == "system":
        head = {**messages[0], "content": f"{messages[0]['content']}\n\n{instructions}"}
        return [head, *messages[1:]]
    return [{"role": "system", "content": instructions}, *messages]

"""The two API shapes a task can speak: `/v1/chat/completions` and `/v1/completions`.

Both build a request body from a conversation and read a response back into a
`Completion`. They differ in how the conversation travels — a messages array or
a prompt rendered from a chat template — and in how a tool call is expressed: a
native `tool_calls` field or a `<tool_call>` block inside the response text.
Each shape therefore also owns the messages an agentic loop appends to continue
its conversation.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from chat_templates import SYSTEM, render_prompt
from config import COMPLETIONS, TaskConfig
from templates import Message
from tools import Tool, ToolCall, describe, parse_tool_calls


@dataclass(frozen=True)
class Completion:
    """One model response: its text, the tools it asked for, and the metadata recorded for it."""

    text: str | None
    meta: dict[str, Any]
    #: Tool calls the model requested; empty when it answered with text.
    tool_calls: tuple[ToolCall, ...] = ()


class Endpoint(ABC):
    """How one API shape builds requests, reads responses and continues a conversation."""

    path: str

    @abstractmethod
    def payload(
        self, messages: Sequence[Message], model: str, temperature: float, max_tokens: int, tools: Sequence[Tool]
    ) -> dict[str, Any]:
        """The request body for one generation."""

    @abstractmethod
    def completion(self, body: dict[str, Any], model: str, latency_ms: int) -> Completion:
        """The response body read into a completion."""

    @abstractmethod
    def assistant_message(self, completion: Completion) -> Message:
        """The conversation turn recording a response that asked for tools."""

    @abstractmethod
    def tool_message(self, call: ToolCall, result: str) -> Message:
        """The conversation turn handing one tool's result back to the model."""


class ChatEndpoint(Endpoint):
    """`/v1/chat/completions`: a messages array and native tool calls."""

    path = "/v1/chat/completions"

    def payload(
        self, messages: Sequence[Message], model: str, temperature: float, max_tokens: int, tools: Sequence[Tool]
    ) -> dict[str, Any]:
        body = {"model": model, "messages": list(messages), "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": tool.definition} for tool in tools]
        return body

    def completion(self, body: dict[str, Any], model: str, latency_ms: int) -> Completion:
        choice = body["choices"][0]
        message = choice["message"]
        return Completion(
            text=message.get("content"),
            meta=_meta(body, choice, model, latency_ms),
            tool_calls=tuple(_call(entry) for entry in message.get("tool_calls") or ()),
        )

    def assistant_message(self, completion: Completion) -> Message:
        return {
            "role": "assistant",
            "content": completion.text,
            "tool_calls": [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.args)}}
                for call in completion.tool_calls
            ],
        }

    def tool_message(self, call: ToolCall, result: str) -> Message:
        return {"role": "tool", "tool_call_id": call.id, "content": result}


class CompletionsEndpoint(Endpoint):
    """`/v1/completions`: a templated prompt string and tool calls written as text blocks."""

    path = "/v1/completions"

    def __init__(self, template: str) -> None:
        self._template = template

    def payload(
        self, messages: Sequence[Message], model: str, temperature: float, max_tokens: int, tools: Sequence[Tool]
    ) -> dict[str, Any]:
        return {
            "model": model,
            "prompt": render_prompt(self._template, _with_tools(messages, tools)),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def completion(self, body: dict[str, Any], model: str, latency_ms: int) -> Completion:
        choice = body["choices"][0]
        text = choice["text"]
        return Completion(text=text, meta=_meta(body, choice, model, latency_ms), tool_calls=parse_tool_calls(text))

    def assistant_message(self, completion: Completion) -> Message:
        return {"role": "assistant", "content": completion.text}

    def tool_message(self, call: ToolCall, result: str) -> Message:
        return {"role": "tool", "content": result}


def build_endpoint(task: TaskConfig) -> Endpoint:
    """The API shape a task's requests use."""
    if task.api_type == COMPLETIONS:
        return CompletionsEndpoint(task.chat_template)
    return ChatEndpoint()


def _meta(body: dict[str, Any], choice: dict[str, Any], model: str, latency_ms: int) -> dict[str, Any]:
    """The metadata recorded for one request, whichever endpoint answered it."""
    usage = body.get("usage", {})
    return {
        "model": body.get("model", model),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "latency_ms": latency_ms,
        "finish_reason": choice.get("finish_reason"),
    }


def _call(entry: dict[str, Any]) -> ToolCall:
    """One native tool call, with its JSON-encoded arguments parsed."""
    function = entry["function"]
    return ToolCall(id=entry["id"], name=function["name"], args=json.loads(function["arguments"]))


def _with_tools(messages: Sequence[Message], tools: Sequence[Tool]) -> list[Message]:
    """The conversation with the tool instructions folded into its system turn."""
    if not tools:
        return list(messages)

    instructions = describe(tools)
    if messages and messages[0]["role"] == SYSTEM:
        first = {**messages[0], "content": f"{messages[0]['content']}\n\n{instructions}"}
        return [first, *messages[1:]]
    return [{"role": SYSTEM, "content": instructions}, *messages]

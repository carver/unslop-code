"""An in-process fake of the OpenAI-compatible API, chat and completions.

The tests drive the CLI as a subprocess, so the server lives in the test
process and is scripted with plain Python callables.  A responder receives the
decoded request payload plus a zero-based call index and returns a ``Reply``.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


@dataclass
class Reply:
    """One scripted HTTP response."""

    body: dict | str
    status: int = 200
    delay: float = 0.0


def completion(
    content: str,
    *,
    model: str = "gpt-4",
    prompt_tokens: int = 30,
    completion_tokens: int = 10,
    finish_reason: str = "stop",
) -> dict:
    """Build a standard OpenAI-style chat completion body."""
    return {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call(name: str, arguments: dict, call_id: str | None = None) -> dict:
    """One OpenAI tool call entry; `arguments` travels as a JSON string."""
    return {
        "id": call_id or f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def tool_call_completion(calls: list, **kwargs) -> dict:
    """A chat completion whose assistant message only requests tools."""
    body = completion(None, finish_reason="tool_calls", **kwargs)
    body["choices"][0]["message"]["tool_calls"] = calls
    return body


def text_completion(text: str, *, finish_reason: str = "stop", **kwargs) -> dict:
    """A `/v1/completions` body, which carries `choices[].text`."""
    body = completion("", finish_reason=finish_reason, **kwargs)
    body["choices"][0] = {"index": 0, "text": text, "finish_reason": finish_reason}
    return body


def tool_call_block(name: str, arguments: dict) -> str:
    """The `<tool_call>` text block a completions-mode model emits."""
    call = json.dumps({"name": name, "arguments": arguments})
    return f"<tool_call>\n{call}\n</tool_call>"


def tools_of(payload: dict) -> list:
    """The tool declarations sent with a chat request."""
    return payload.get("tools") or []


def tool_results_of(payload: dict) -> list:
    """The tool results already fed back into a chat conversation."""
    return [m["content"] for m in payload["messages"] if m["role"] == "tool"]


def turns_of(payload: dict) -> list:
    """The `(role, content)` pairs of a chat request."""
    return [(m["role"], m.get("content")) for m in payload["messages"]]


def system_of(payload: dict) -> str:
    """The system message of a request, or an empty string when absent."""
    systems = [m["content"] for m in payload["messages"] if m["role"] == "system"]
    return systems[0] if systems else ""


def user_of(payload: dict) -> str:
    """The last user message of a request."""
    return [m["content"] for m in payload["messages"] if m["role"] == "user"][-1]


def assistants_of(payload: dict) -> list:
    """The assistant messages of a request, in order: the ICL example answers."""
    return [m["content"] for m in payload["messages"] if m["role"] == "assistant"]


def always(content: str, **kwargs) -> Callable[[dict, int], Reply]:
    """Responder that answers every request with the same content."""
    return lambda payload, index: Reply(completion(content, **kwargs))


def cycle(contents: list[str], **kwargs) -> Callable[[dict, int], Reply]:
    """Responder that walks a list of contents, repeating the last one."""

    def responder(payload: dict, index: int) -> Reply:
        return Reply(completion(contents[min(index, len(contents) - 1)], **kwargs))

    return responder


def echo_user(**kwargs) -> Callable[[dict, int], Reply]:
    """Responder that answers with the rendered user prompt."""

    def responder(payload: dict, index: int) -> Reply:
        user = [m for m in payload["messages"] if m["role"] == "user"][-1]
        return Reply(completion(user["content"], **kwargs))

    return responder


def turn_index(payload: dict) -> int:
    """How many assistant turns a conversation already holds.

    Agentic responders key off this rather than the global request index so
    that rows running concurrently each get their own scripted sequence.
    """
    if "messages" in payload:
        return sum(1 for m in payload["messages"] if m["role"] == "assistant")
    # A completions prompt shows the tag once in its tool instructions, then
    # once more for every tool-call turn already replayed into it.
    return max(0, payload["prompt"].count("</tool_call>") - 1)


def conversation(replies: list, **kwargs) -> Callable[[dict, int], Reply]:
    """Responder walking `replies` by conversation turn, repeating the last.

    A plain string entry becomes a final answer; a list of tool calls becomes
    a tool-call response in whichever shape the request used.
    """

    def responder(payload: dict, index: int) -> Reply:
        entry = replies[min(turn_index(payload), len(replies) - 1)]
        if isinstance(entry, Reply):
            return entry
        return Reply(_body(entry, "prompt" in payload, **kwargs))

    return responder


def _body(entry, completions_mode: bool, **kwargs) -> dict:
    """The response body for one scripted turn, matching the request's shape."""
    if isinstance(entry, str):
        return text_completion(entry, **kwargs) if completions_mode else completion(entry, **kwargs)
    if completions_mode:
        blocks = "\n".join(tool_call_block(name, args) for name, args in entry)
        return text_completion(blocks, finish_reason="tool_calls", **kwargs)
    return tool_call_completion([tool_call(name, args) for name, args in entry], **kwargs)


@dataclass
class _State:
    responder: Callable[[dict, int], Reply]
    capacity: threading.Semaphore
    lock: threading.Lock = field(default_factory=threading.Lock)
    requests: list = field(default_factory=list)
    in_flight: int = 0
    peak_in_flight: int = 0


class _Server(ThreadingHTTPServer):
    """Accepts a deep backlog so a burst of connections is not serialised."""

    daemon_threads = True
    request_queue_size = 128


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        state: _State = self.server.state

        with state.lock:
            index = len(state.requests)
            state.requests.append({"path": self.path, "payload": payload})
            state.in_flight += 1
            state.peak_in_flight = max(state.peak_in_flight, state.in_flight)

        reply = state.responder(payload, index)
        with state.capacity:
            time.sleep(reply.delay)

        with state.lock:
            state.in_flight -= 1

        raw = reply.body if isinstance(reply.body, str) else json.dumps(reply.body)
        encoded = raw.encode()
        self.send_response(reply.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:
        """Silence the default stderr access log."""


class FakeAPIServer:
    """Threaded HTTP server exposing ``/v1/chat/completions``.

    ``capacity`` bounds how many requests are processed at once; additional
    requests wait, which models the queueing server described by the spec.
    """

    def __init__(self, responder: Callable[[dict, int], Reply], capacity: int = 64):
        self._httpd = _Server(("127.0.0.1", 0), _Handler)
        self._httpd.state = _State(responder, threading.Semaphore(capacity))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FakeAPIServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list:
        with self._httpd.state.lock:
            return list(self._httpd.state.requests)

    @property
    def payloads(self) -> list:
        return [entry["payload"] for entry in self.requests]

    @property
    def paths(self) -> list:
        return [entry["path"] for entry in self.requests]

    @property
    def peak_in_flight(self) -> int:
        return self._httpd.state.peak_in_flight

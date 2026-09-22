"""A minimal OpenAI-compatible chat completions server used by the tests.

The real server described by the spec queues requests internally and spends
time on each one, so the mock models the same thing: `workers` requests are
served at a time, each taking `service_time` seconds. That gives a known
request capacity of ``60 * workers / service_time`` per minute, which the
throughput tests compare against the configured ``rpm``.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

COMPLETIONS_PATH = "/v1/completions"


@dataclass
class Reply:
    """One scripted model response: final text, tool calls, or both.

    ``tool_calls`` entries are ``{"name": ..., "arguments": {...}}``; the
    server renders them as OpenAI ``tool_calls`` on the chat endpoint and as
    ``<tool_call>`` text blocks on the completions endpoint.
    """

    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None

    @property
    def reason(self) -> str:
        if self.finish_reason is not None:
            return self.finish_reason
        return "tool_calls" if self.tool_calls else "stop"


@dataclass
class Script:
    """Per-call behaviour for the mock server.

    ``contents`` supplies response text call by call (the last entry repeats).
    ``fail_status`` is returned for the call indexes listed in ``fail_calls``,
    and for every request whose body contains ``fail_if_contains`` (useful when
    concurrency makes call indexes unpredictable). ``content_if_contains`` maps
    a marker to the reply used for any request whose body contains it, which is
    how judge calls are told apart from generation calls.
    """

    contents: list[str] = field(default_factory=lambda: ["#### 42"])
    content_if_contains: dict[str, str] = field(default_factory=dict)
    fail_calls: set[int] = field(default_factory=set)
    fail_if_contains: str | None = None
    fail_status: int = 503
    prompt_tokens: int = 45
    completion_tokens: int = 120
    service_time: float = 0.0
    workers: int = 8
    responder: Callable[[dict, str, int], Reply] | None = None


class MockServer:
    """Threaded HTTP server exposing ``POST /v1/chat/completions`` and
    ``POST /v1/completions``."""

    def __init__(self, script: Script | None = None):
        self.script = script or Script()
        self.payloads: list[dict] = []
        self.paths: list[str] = []
        self.arrivals: list[float] = []
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(self.script.workers)
        self._active = 0
        self.peak_concurrency = 0
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> "MockServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.payloads)

    def record(self, path: str, payload: dict) -> int:
        """Store a request with its arrival time, returning its call index."""
        with self._lock:
            self.paths.append(path)
            self.payloads.append(payload)
            self.arrivals.append(time.monotonic())
            return len(self.payloads) - 1

    def serve(self, index: int, payload: dict, path: str) -> tuple[int, dict]:
        """Occupy a worker slot for ``service_time`` and build the reply."""
        self._enter()
        try:
            with self._slots:
                time.sleep(self.script.service_time)
        finally:
            self._leave()
        body = json.dumps(payload)
        marker = self.script.fail_if_contains
        if index in self.script.fail_calls or (marker is not None and marker in body):
            return self.script.fail_status, {"error": "server error"}
        reply = self._reply(index, payload, path, body)
        choice = (
            _text_choice(reply)
            if path.endswith(COMPLETIONS_PATH)
            else _message_choice(reply, index)
        )
        return 200, {
            "id": f"chatcmpl-{index}",
            "choices": [{"index": 0, **choice}],
            "usage": {
                "prompt_tokens": self.script.prompt_tokens,
                "completion_tokens": self.script.completion_tokens,
                "total_tokens": self.script.prompt_tokens + self.script.completion_tokens,
            },
        }

    def _enter(self) -> None:
        """Count one request as in flight, tracking the peak seen so far."""
        with self._lock:
            self._active += 1
            self.peak_concurrency = max(self.peak_concurrency, self._active)

    def _leave(self) -> None:
        with self._lock:
            self._active -= 1

    def _reply(self, index: int, payload: dict, path: str, body: str) -> Reply:
        """The scripted reply for one request, by responder or by call index."""
        if self.script.responder is not None:
            return self.script.responder(payload, path, index)
        contents = self.script.contents
        content = contents[min(index, len(contents) - 1)]
        for needle, text in self.script.content_if_contains.items():
            if needle in body:
                content = text
                break
        return Reply(content=content)


def _message_choice(reply: Reply, index: int) -> dict:
    """The chat shape: an assistant message, with `tool_calls` when scripted."""
    message = {"role": "assistant", "content": reply.content}
    if reply.tool_calls:
        message["tool_calls"] = [
            {
                "id": f"call_{index}_{position}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call.get("arguments", {})),
                },
            }
            for position, call in enumerate(reply.tool_calls)
        ]
    return {"message": message, "finish_reason": reply.reason}


def _text_choice(reply: Reply) -> dict:
    """The completions shape: plain text, with `<tool_call>` blocks inline."""
    parts = [reply.content] if reply.content else []
    parts += [
        "<tool_call>\n" + json.dumps(call) + "\n</tool_call>"
        for call in reply.tool_calls
    ]
    return {"text": "\n".join(parts), "finish_reason": reply.reason}


def _make_handler(server: MockServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            request = json.loads(body)
            index = server.record(self.path, request)
            status, payload = server.serve(index, request, self.path)
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    return Handler

"""A minimal OpenAI-compatible chat completions server for tests.

The real server described by the spec "queues requests internally and spends
time processing each request", so this stand-in models capacity with a
semaphore of `slots` workers each taking `delay` seconds per request. That
makes a sequential client measurably slower than a concurrent one.
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
    """What the fake server should do for one request."""

    content: str = "#### 42"
    status: int = 200
    finish_reason: str = "stop"
    prompt_tokens: int = 10
    completion_tokens: int = 20


# A responder maps (call_index, request_body) -> Reply.
Responder = Callable[[int, dict], Reply]


def always(content: str, **kwargs) -> Responder:
    """Responder that answers every request identically."""
    return lambda index, body: Reply(content=content, **kwargs)


def sequence(replies: list[Reply]) -> Responder:
    """Responder that walks a fixed script, repeating the last entry."""
    return lambda index, body: replies[min(index, len(replies) - 1)]


def by_question(mapping: dict[str, Reply], default: Reply | None = None) -> Responder:
    """Responder keyed on the rendered user message, for order-safety checks."""

    def respond(index: int, body: dict) -> Reply:
        user = body["messages"][-1]["content"]
        return mapping.get(user, default or Reply(content="unmapped"))

    return respond


@dataclass
class FakeAPI:
    """Threaded fake API; use as a context manager and read `url`."""

    responder: Responder = field(default_factory=lambda: always("#### 42"))
    slots: int = 8
    delay: float = 0.05

    def __post_init__(self) -> None:
        self.requests: list[dict] = []
        self.paths: list[str] = []
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(self.slots)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def next_reply(self, body: dict) -> Reply:
        with self._lock:
            index = len(self.requests)
            self.requests.append(body)
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        return self.responder(index, body)

    def finish_one(self) -> None:
        with self._lock:
            self._active -= 1

    def serve(self, body: dict) -> Reply:
        """Apply capacity limits and processing time, then answer."""
        reply = self.next_reply(body)
        with self._slots:
            time.sleep(self.delay)
        self.finish_one()
        return reply

    def __enter__(self) -> "FakeAPI":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()


def _make_handler(api: FakeAPI):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            api.paths.append(self.path)
            reply = api.serve(body)
            if reply.status != 200:
                self._send(reply.status, {"error": {"message": "boom"}})
                return
            self._send(200, _completion(body.get("model", "unknown"), reply))

        def _send(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args) -> None:
            pass

    return Handler


def _completion(model: str, reply: Reply) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply.content},
                "finish_reason": reply.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "total_tokens": reply.prompt_tokens + reply.completion_tokens,
        },
    }

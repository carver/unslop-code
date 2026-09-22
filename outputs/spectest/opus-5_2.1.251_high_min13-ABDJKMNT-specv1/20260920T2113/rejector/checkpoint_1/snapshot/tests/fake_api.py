"""A threaded, OpenAI-compatible stand-in for the chat completions API.

The real server described by the spec queues requests internally and spends time
processing each one. This stand-in reproduces that shape: an optional per-request
delay, a scriptable response per request, and a log the tests assert against
(request bodies, arrival order, observed concurrency).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHAT_PATH = "/v1/chat/completions"


@dataclass
class Call:
    """One HTTP request as seen by the server."""

    index: int
    path: str
    body: dict
    started: float


@dataclass
class Log:
    """Everything the tests need to know about traffic the server received."""

    calls: list[Call] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0

    @property
    def bodies(self) -> list[dict]:
        return [call.body for call in self.calls]

    @property
    def user_prompts(self) -> list[str]:
        return [call.body["messages"][-1]["content"] for call in self.calls]


def ok(content: str, *, prompt_tokens: int = 10, completion_tokens: int = 5,
       finish_reason: str = "stop", model: str = "gpt-4") -> dict:
    """A well-formed chat completion response payload."""
    return {
        "status": 200,
        "payload": {
            "id": "chatcmpl-fake",
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
        },
    }


def error(status: int, message: str = "boom") -> dict:
    """A non-2xx response."""
    return {"status": status, "payload": {"error": {"message": message}}}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler naming
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        server: FakeAPI = self.server.fake  # type: ignore[attr-defined]
        index = server._begin(self.path, body)
        try:
            if server.delay:
                time.sleep(server.delay)
            spec = server.responder(index, body)
        finally:
            server._end()
        raw = json.dumps(spec.get("payload", {})).encode()
        self.send_response(spec.get("status", 200))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # silence stderr chatter
        pass


class FakeAPI:
    """Context manager exposing ``url`` and a ``log`` of received requests."""

    def __init__(self, responder=None, delay: float = 0.0):
        self.responder = responder or (lambda index, body: ok(f"#### {index}"))
        self.delay = delay
        self.log = Log()
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.fake = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _begin(self, path: str, body: dict) -> int:
        with self._lock:
            index = len(self.log.calls)
            self.log.calls.append(Call(index, path, body, time.monotonic()))
            self.log.in_flight += 1
            self.log.max_in_flight = max(self.log.max_in_flight, self.log.in_flight)
            return index

    def _end(self) -> None:
        with self._lock:
            self.log.in_flight -= 1

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeAPI":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

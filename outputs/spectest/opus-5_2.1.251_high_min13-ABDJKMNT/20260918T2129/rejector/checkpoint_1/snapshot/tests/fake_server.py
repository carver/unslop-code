"""An in-process fake of the OpenAI-compatible chat completions API.

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


@dataclass
class _State:
    responder: Callable[[dict, int], Reply]
    capacity: threading.Semaphore
    lock: threading.Lock = field(default_factory=threading.Lock)
    requests: list = field(default_factory=list)
    in_flight: int = 0
    peak_in_flight: int = 0


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
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
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

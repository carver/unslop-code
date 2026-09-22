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


@dataclass
class Script:
    """Per-call behaviour for the mock server.

    ``contents`` supplies response text call by call (the last entry repeats).
    ``fail_status`` is returned for the call indexes listed in ``fail_calls``,
    and for every request whose body contains ``fail_if_contains`` (useful when
    concurrency makes call indexes unpredictable).
    """

    contents: list[str] = field(default_factory=lambda: ["#### 42"])
    fail_calls: set[int] = field(default_factory=set)
    fail_if_contains: str | None = None
    fail_status: int = 503
    prompt_tokens: int = 45
    completion_tokens: int = 120
    service_time: float = 0.0
    workers: int = 8


class MockServer:
    """Threaded HTTP server exposing ``POST /v1/chat/completions``."""

    def __init__(self, script: Script | None = None):
        self.script = script or Script()
        self.payloads: list[dict] = []
        self.paths: list[str] = []
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(self.script.workers)
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
        """Store a request and return its zero-based call index."""
        with self._lock:
            self.paths.append(path)
            self.payloads.append(payload)
            return len(self.payloads) - 1

    def serve(self, index: int, payload: dict) -> tuple[int, dict]:
        """Occupy a worker slot for ``service_time`` and build the reply."""
        with self._slots:
            time.sleep(self.script.service_time)
        marker = self.script.fail_if_contains
        if index in self.script.fail_calls or (
            marker is not None and marker in json.dumps(payload)
        ):
            return self.script.fail_status, {"error": "server error"}
        contents = self.script.contents
        content = contents[min(index, len(contents) - 1)]
        return 200, {
            "id": f"chatcmpl-{index}",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": self.script.prompt_tokens,
                "completion_tokens": self.script.completion_tokens,
                "total_tokens": self.script.prompt_tokens + self.script.completion_tokens,
            },
        }


def _make_handler(server: MockServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            request = json.loads(body)
            index = server.record(self.path, request)
            status, payload = server.serve(index, request)
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    return Handler

"""A stand in for the chat completions API, used by the tests.

The server mimics the real one: requests are queued and served by a limited
number of internal workers, each spending `delay` seconds on a request.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import sleep
from typing import Callable

# A responder receives the request payload and the 1-based index of the call for
# that exact prompt, and returns either response text or an HTTP status to fail with.
Responder = Callable[[dict, int], "str | int"]


@dataclass
class MockAPI:
    """Shared state behind the request handler."""

    responder: Responder
    delay: float
    gate: threading.Semaphore
    lock: threading.Lock = field(default_factory=threading.Lock)
    calls: list[dict] = field(default_factory=list)
    prompt_calls: dict[str, int] = field(default_factory=dict)

    def serve(self, payload: dict) -> str | int:
        """Spend the configured service time, then decide what to answer."""
        with self.gate:
            sleep(self.delay)
            with self.lock:
                prompt = json.dumps(payload["messages"])
                self.prompt_calls[prompt] = self.prompt_calls.get(prompt, 0) + 1
                self.calls.append(payload)
                return self.responder(payload, self.prompt_calls[prompt])


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    api: MockAPI

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        reply = self.api.serve(payload)
        if isinstance(reply, int):
            self._send(reply, {"error": {"message": "mock failure"}})
            return
        self._send(200, _completion(payload["model"], reply))

    def _send(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:  # keep pytest output readable
        pass


def _completion(model: str, text: str) -> dict:
    return {
        "id": "chatcmpl-mock",
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256  # the client opens every connection at once


def start_mock_server(responder: Responder, delay: float = 0.0, capacity: int = 8, port: int = 0):
    """Start the server on `port` (0 picks a free one); returns `(url, api, shutdown)`."""
    api = MockAPI(responder=responder, delay=delay, gate=threading.Semaphore(capacity))
    handler = type("BoundHandler", (_Handler,), {"api": api})
    server = _Server(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", api, server.shutdown


def _summing_responder(wrong_first: int) -> Responder:
    """Add up the numbers in the prompt, after `wrong_first` deliberately wrong answers.

    Summing is enough to "solve" the bundled examples, and the wrong answers make
    the rejection sampling scheme visibly retry.
    """

    def respond(payload: dict, call: int) -> str:
        numbers = re.findall(r"-?\d+", payload["messages"][-1]["content"])
        total = sum(int(number) for number in numbers) if call > wrong_first else 0
        return f"Let me work through it step by step.\n#### {total}"

    return respond


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the mock chat completions API.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--delay", type=float, default=0.5, help="service time per request")
    parser.add_argument("--capacity", type=int, default=8, help="requests served in parallel")
    parser.add_argument("--wrong-first", type=int, default=0, help="wrong answers per prompt")
    options = parser.parse_args()
    responder = _summing_responder(options.wrong_first)
    url, _, _ = start_mock_server(responder, options.delay, options.capacity, options.port)
    print(f"mock API listening on {url}", flush=True)
    threading.Event().wait()

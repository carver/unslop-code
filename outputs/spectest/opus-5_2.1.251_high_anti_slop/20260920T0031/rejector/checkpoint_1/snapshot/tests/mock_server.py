#!/usr/bin/env python3
"""Mock OpenAI-compatible server used to exercise the CLI end to end.

It processes a bounded number of requests at a time (so extra requests queue
rather than being rejected) and answers with the last number found in the user
message, which lets `exact_match` + `last_number` evaluation be predicted.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class Settings:
    """Server behaviour knobs shared by all handler threads."""

    def __init__(self, rpm: int, latency: float, fail_rate: float, accuracy: float) -> None:
        self.latency = latency
        self.fail_rate = fail_rate
        self.accuracy = accuracy
        self.slots = threading.Semaphore(max(1, round(rpm * latency / 60)))
        self.lock = threading.Lock()
        self.calls = 0
        self.peak_in_flight = 0
        self.in_flight = 0


class Server(ThreadingHTTPServer):
    """Accepts a deep backlog so a burst of concurrent clients is queued, not refused."""

    daemon_threads = True
    request_queue_size = 256


class Handler(BaseHTTPRequestHandler):
    settings: Settings
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._track(+1)
        with self.settings.slots:
            time.sleep(self.settings.latency)
        self._track(-1)

        if random.random() < self.settings.fail_rate:
            self._respond(503, {"error": "overloaded"})
            return
        self._respond(200, self._completion(body))

    def _completion(self, body: dict) -> dict:
        prompt = " ".join(message["content"] for message in body["messages"] if message["role"] == "user")
        numbers = NUMBER.findall(prompt)
        answer = numbers[-1] if numbers else "0"
        if random.random() >= self.settings.accuracy:
            answer = str(float(answer) + 1)
        return {
            "id": "chatcmpl-mock",
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"Working it out.\n#### {answer}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def _track(self, delta: int) -> None:
        with self.settings.lock:
            self.settings.in_flight += delta
            self.settings.calls += delta > 0
            self.settings.peak_in_flight = max(self.settings.peak_in_flight, self.settings.in_flight)

    def _respond(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args) -> None:
        """Silence per-request logging."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rpm", type=int, default=60, help="requests per minute the server can process")
    parser.add_argument("--latency", type=float, default=1.0, help="seconds spent on each request")
    parser.add_argument("--fail-rate", type=float, default=0.0, help="fraction of requests answered with a 503")
    parser.add_argument("--accuracy", type=float, default=1.0, help="fraction of responses with the right answer")
    args = parser.parse_args()

    Handler.settings = Settings(args.rpm, args.latency, args.fail_rate, args.accuracy)
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"mock server on :{args.port} rpm={args.rpm} latency={args.latency}s", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

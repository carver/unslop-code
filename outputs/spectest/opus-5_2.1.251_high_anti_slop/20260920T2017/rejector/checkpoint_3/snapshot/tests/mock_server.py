#!/usr/bin/env python3
"""Mock OpenAI-compatible server used to exercise the CLI.

It emulates a backend with a fixed number of workers, each taking `--delay`
seconds per request, so its capacity is `workers / delay * 60` requests per
minute. Requests beyond that queue up inside the server.

The reply echoes the `ANSWER=<value>` marker found in the user prompt, which
lets tests control whether a response passes evaluation. When the request
carries in-context examples, the reply also echoes an `ICL=<count>:<first
assistant turn>` line, so tests can see which setup was prompted with.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER_MARKER = re.compile(r"ANSWER=(\S+)")


class Backend:
    """Shared state: worker capacity, per-prompt attempt counts, error injection."""

    def __init__(self, workers: int, delay: float, pass_after: int, pass_every: int,
                 fail_500: int, always_500: bool):
        self.slots = threading.Semaphore(workers)
        self.delay = delay
        self.pass_after = pass_after
        self.pass_every = pass_every
        self.always_500 = always_500
        self._lock = threading.Lock()
        self._remaining_500 = fail_500
        self._calls = itertools.count(1)
        self._attempts: dict[str, int] = defaultdict(int)

    def handle(self, prompt: str, examples: list[str]) -> tuple[int, dict]:
        with self._lock:
            call = next(self._calls)
            self._attempts[prompt] += 1
            attempt = self._attempts[prompt]
            inject_500 = self.always_500 or self._remaining_500 > 0
            if self._remaining_500 > 0:
                self._remaining_500 -= 1

        with self.slots:
            time.sleep(self.delay)

        if inject_500:
            return 500, {"error": "backend overloaded"}
        answer = ANSWER_MARKER.search(prompt)
        passes = attempt >= self.pass_after and attempt % self.pass_every == 0
        value = answer.group(1) if answer and passes else "0"
        icl = f"\nICL={len(examples)}:{examples[0]}" if examples else ""
        return 200, {
            "id": f"chatcmpl-{call}",
            "model": "mock-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"Working it out.{icl}\n#### {value}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


class QueueingServer(ThreadingHTTPServer):
    """A deep listen backlog: connections wait rather than being refused."""

    request_queue_size = 256
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    backend: Backend

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages = body["messages"]
        examples = [message["content"] for message in messages if message["role"] == "assistant"]
        status, payload = self.backend.handle(messages[-1]["content"], examples)
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:
        """Keep the test output quiet."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=1, help="concurrent requests served")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds spent per request")
    parser.add_argument("--pass-after", type=int, default=1, help="per-prompt attempt that passes")
    parser.add_argument("--pass-every", type=int, default=1, help="only every Nth attempt passes")
    parser.add_argument("--fail-500", type=int, default=0, help="first N requests answer 500")
    parser.add_argument("--always-500", action="store_true")
    args = parser.parse_args()

    Handler.backend = Backend(args.workers, args.delay, args.pass_after, args.pass_every,
                              args.fail_500, args.always_500)
    server = QueueingServer(("127.0.0.1", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

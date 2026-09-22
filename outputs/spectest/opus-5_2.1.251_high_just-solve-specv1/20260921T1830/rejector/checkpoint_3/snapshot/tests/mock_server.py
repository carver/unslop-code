#!/usr/bin/env python3
"""Mock OpenAI-compatible chat completions server used by the test suite.

Models a server that queues requests internally: it processes at most
``capacity`` requests at a time, each taking ``latency`` seconds. Overall
throughput therefore caps at ``capacity / latency`` requests per second, and a
sequential client can never exceed ``1 / latency``.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE_LOCK = threading.Lock()
SEEN: dict[str, int] = {}
ARRIVALS: list[str] = []
MAX_INFLIGHT = 0
INFLIGHT = 0
TOTAL = 0

ARITH_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)")


def solve(question: str) -> str:
    match = ARITH_RE.search(question)
    if not match:
        return "0"
    left, op, right = float(match.group(1)), match.group(2), float(match.group(3))
    value = {"+": left + right, "-": left - right, "*": left * right,
             "/": left / right if right else 0.0}[op]
    return str(int(value)) if float(value).is_integer() else str(value)


def completion(request: dict, content: str) -> dict:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.get("model", "mock"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MockOpenAI/1.0"
    capacity_sem: threading.Semaphore
    latency: float

    def log_message(self, *args):  # silence access logs
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/stats":
            with STATE_LOCK:
                self._send(200, {"max_inflight": MAX_INFLIGHT, "total": TOTAL,
                                 "arrivals": ARRIVALS})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        global INFLIGHT, MAX_INFLIGHT, TOTAL
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": {"message": "unknown route"}})
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": {"message": "invalid JSON"}})
            return

        messages = request.get("messages", [])
        user = ""
        system = ""
        for message in messages:
            if message.get("role") == "user":
                user = message.get("content", "")
            elif message.get("role") == "system":
                system = message.get("content", "")

        with STATE_LOCK:
            INFLIGHT += 1
            TOTAL += 1
            MAX_INFLIGHT = max(MAX_INFLIGHT, INFLIGHT)
            SEEN[user] = SEEN.get(user, 0) + 1
            ARRIVALS.append(user)
            nth = SEEN[user]

        with self.capacity_sem:
            time.sleep(self.latency)

        with STATE_LOCK:
            INFLIGHT -= 1

        # Failure injection driven by markers in the prompt.
        if "ALWAYS_500" in user:
            self._send(503, {"error": {"message": "server overloaded"}})
            return
        if "FLAKY2" in user and nth <= 2:
            self._send(500, {"error": {"message": "transient"}})
            return
        if "BAD_REQUEST" in user:
            self._send(400, {"error": {"message": "bad request"}})
            return

        # Judge requests: identified by a JUDGE marker in the system prompt.
        # The score comes from a SCORE=<n> marker anywhere in the prompt.
        if "JUDGE" in system or "evaluator" in system.lower():
            # SCORE=8 or SCORE=3,4,9 (one value per repeat of the same prompt).
            marker = re.search(r"SCORE=([0-9.,+-]+)", user)
            scores = [v for v in marker.group(1).split(",") if v] if marker else ["8"]
            self._send(200, completion(request, scores[min(nth - 1, len(scores) - 1)]))
            return

        # SAY:<text> replies verbatim (\n escapes become newlines).
        say = re.search(r"SAY:(.*)", user, re.S)
        if say:
            self._send(200, completion(request, say.group(1).replace("\\n", "\n")))
            return

        correct = solve(user)
        reject = re.search(r"REJECT(\d+)", user)
        if reject and nth <= int(reject.group(1)):
            content = f"Thinking about it.\n#### {int(float(correct)) + 100}"
        elif "NEVER" in user:
            content = "Thinking about it.\n#### 999999"
        else:
            content = f"Let me solve this step by step.\n{user.strip()}\n#### {correct}"

        self._send(200, completion(request, content))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--capacity", type=int, default=2, help="parallel processing slots")
    parser.add_argument("--latency", type=float, default=2.0, help="seconds per request")
    args = parser.parse_args()

    Handler.capacity_sem = threading.Semaphore(args.capacity)
    Handler.latency = args.latency

    ThreadingHTTPServer.request_queue_size = 1024  # avoid accept-backlog reordering
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"mock server on 127.0.0.1:{args.port} capacity={args.capacity} latency={args.latency}s",
          flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

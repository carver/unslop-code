#!/usr/bin/env python3
"""Mock OpenAI-compatible server for the part 5 tests.

Adds JSON (structured output) replies, configurable token usage and a
per-question flaky mode, on top of a worker-pool queue like mock_server.py.
"""
import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {
    "workers": 10,
    "latency": 0.05,
    "mode": "json",
    "fail_n": 1,
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "calls": 0,
    "inflight": 0,
    "max_inflight": 0,
    "times": [],
}
SEM = None
LOCK = threading.Lock()


class Server(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/stats":
            with LOCK:
                body = json.dumps({
                    "calls": STATE["calls"],
                    "max_inflight": STATE["max_inflight"],
                    "times": STATE["times"],
                }).encode()
            self._send(200, body)
        else:
            self._send(404, b"{}")

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/v1/completions"):
            self._send(404, b'{"error":"not found"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        with LOCK:
            STATE["calls"] += 1
            index = STATE["calls"]
            STATE["times"].append(time.time())
            STATE["inflight"] += 1
            STATE["max_inflight"] = max(STATE["max_inflight"], STATE["inflight"])
        try:
            with SEM:
                time.sleep(STATE["latency"])
                self._send(200, self._body(payload, index))
        finally:
            with LOCK:
                STATE["inflight"] -= 1

    def _text(self, payload):
        user = ""
        if self.path == "/v1/completions":
            user = payload.get("prompt", "")
        else:
            for msg in payload.get("messages", []):
                if msg.get("role") == "user":
                    user = msg.get("content", "")
        mode = STATE["mode"]
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", user)]
        total = sum(nums)
        total = int(total) if total == int(total) else total
        if mode == "json":
            return json.dumps({"code": f"def f(): return {total}", "explanation": "adds numbers"})
        if mode == "json_missing":
            return json.dumps({"code": f"def f(): return {total}"})
        if mode == "json_bad":
            return "Sure! Here is the code, not JSON at all."
        if mode == "json_flaky":
            with LOCK:
                seen = STATE.setdefault("seen", {})
                seen[user] = seen.get(user, 0) + 1
                count = seen[user]
            if count <= STATE["fail_n"]:
                return "nope, not json"
            return json.dumps({"code": f"def f(): return {total}", "explanation": "adds"})
        if mode == "json_typed":
            return json.dumps({"code": 42, "explanation": "wrong type"})
        return f"Step by step.\n#### {total}"

    def _body(self, payload, index):
        text = self._text(payload)
        usage = {
            "prompt_tokens": STATE["prompt_tokens"],
            "completion_tokens": STATE["completion_tokens"],
            "total_tokens": STATE["prompt_tokens"] + STATE["completion_tokens"],
        }
        if self.path == "/v1/completions":
            body = {"id": f"cmpl-{index}", "model": payload.get("model", "mock"),
                    "choices": [{"index": 0, "text": text, "finish_reason": "stop"}],
                    "usage": usage}
        else:
            body = {"id": f"chatcmpl-{index}", "model": payload.get("model", "mock"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                 "finish_reason": "stop"}],
                    "usage": usage}
        return json.dumps(body).encode()

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global SEM
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--latency", type=float, default=0.05)
    ap.add_argument("--mode", default="json")
    ap.add_argument("--fail-n", type=int, default=1)
    ap.add_argument("--prompt-tokens", type=int, default=10)
    ap.add_argument("--completion-tokens", type=int, default=5)
    args = ap.parse_args()
    STATE.update(workers=args.workers, latency=args.latency, mode=args.mode,
                 fail_n=args.fail_n, prompt_tokens=args.prompt_tokens,
                 completion_tokens=args.completion_tokens)
    SEM = threading.BoundedSemaphore(args.workers)
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"mock5 on {args.port} mode={args.mode}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

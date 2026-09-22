#!/usr/bin/env python3
"""Mock OpenAI-compatible server.

Queues requests internally: at most `workers` are processed at once and each
takes `latency` seconds, so sustained capacity is workers/latency req/sec.
Never returns rate-limit errors; excess requests simply wait.
"""
import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY_RE = re.compile(r"key:([a-z0-9_]+)")
EXPR_RE = re.compile(r"calc:([0-9+\-*/ ().]+?)(?=[\s,.?]|$)")

STATE = {
    "workers": 10,
    "latency": 1.0,
    "mode": "solve",       # solve|fail|flaky|fail_nth|always500|mixed|agent|agent_never
    "fail_n": 2,           # for flaky/fail_nth
    "judge_score": "8",    # for mixed mode (llm_judge replies)
    "letter": "B",         # for mixed mode (multiple-choice replies)
    "calls": 0,
    "max_inflight": 0,
    "inflight": 0,
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
        if self.path == "/payloads":
            with LOCK:
                body = json.dumps(STATE.get("payloads", [])).encode()
            self._send(200, body)
        elif self.path == "/stats":
            with LOCK:
                body = json.dumps(
                    {"calls": STATE["calls"], "max_inflight": STATE["max_inflight"]}
                ).encode()
            self._send(200, body)
        else:
            self._send(404, b"{}")

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/v1/completions"):
            self._send(404, b'{"error":"not found"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except ValueError:
            self._send(400, b'{"error":"bad json"}')
            return

        with LOCK:
            STATE.setdefault("payloads", []).append(
                {"body": payload, "headers": dict(self.headers), "path": self.path}
            )
            STATE["calls"] += 1
            call_index = STATE["calls"]
            STATE["inflight"] += 1
            STATE["max_inflight"] = max(STATE["max_inflight"], STATE["inflight"])

        try:
            with SEM:
                time.sleep(STATE["latency"])
                self._respond(payload, call_index)
        finally:
            with LOCK:
                STATE["inflight"] -= 1

    def _respond(self, payload, call_index):
        mode = STATE["mode"]
        if mode == "always500":
            self._send(500, b'{"error":"boom"}')
            return

        completions = self.path == "/v1/completions"
        user = ""
        system = ""
        tool_results = ""
        if completions:
            user = payload.get("prompt", "") or ""
            system = user
            if user.count("</tool_call>") >= 2:
                tool_results = user.rsplit("</tool_call>", 1)[1]
        else:
            for msg in payload.get("messages", []):
                if msg.get("role") == "user":
                    user = msg.get("content", "")
                elif msg.get("role") == "system":
                    system = msg.get("content", "")
                elif msg.get("role") == "tool":
                    tool_results += (msg.get("content") or "") + "\n"
        question = user

        if mode.startswith("agent"):
            self._send(200, self._agentic_body(payload, call_index, mode, user, tool_results,
                                               completions))
            return

        if mode == "mixed":
            self._send(200, self._body(payload, call_index, mixed_reply(system, user)))
            return

        if mode == "fail_nth":
            # deterministic per question: first fail_n HTTP calls 503, then succeed
            with LOCK:
                seen5 = STATE.setdefault("seen5xx", {})
                seen5[question] = seen5.get(question, 0) + 1
                count5 = seen5[question]
            if count5 <= STATE["fail_n"]:
                self._send(503, b'{"error":"unavailable"}')
                return

        answer = solve(question)
        temp = payload.get("temperature", 0.0)

        if mode == "fail":
            text = "I think the answer is\n#### 999"
        elif mode == "flaky":
            # deterministic: first fail_n calls per-question fail, then succeed
            key = question
            with LOCK:
                seen = STATE.setdefault("seen", {})
                seen[key] = seen.get(key, 0) + 1
                count = seen[key]
            if count <= STATE["fail_n"]:
                text = "Hmm.\n#### 999"
            else:
                text = f"Let me think.\n#### {answer}"
        else:
            text = f"Step by step.\n#### {answer}"

        self._send(200, self._body(payload, call_index, text))

    def _agentic_body(self, payload, call_index, mode, text, tool_results, completions):
        """Ask for tools until their results are in the conversation, then answer."""
        keys = []
        for key in KEY_RE.findall(text):
            if key not in keys:
                keys.append(key)
        exprs = EXPR_RE.findall(text)

        calls = []
        if mode == "agent_never":
            calls = [{"name": "lookup", "arguments": {"key": keys[0] if keys else "employees"}}]
        elif not tool_results.strip():
            for key in keys:
                calls.append({"name": "lookup", "arguments": {"key": key}})
            for expr in exprs:
                calls.append({"name": "calculate", "arguments": {"code": f"print({expr})"}})
            if "slowcalc" in text:
                calls.append(
                    {"name": "calculate", "arguments": {"code": "import time; time.sleep(30)"}}
                )

        if calls:
            if completions:
                blocks = "\n".join(
                    "<tool_call>\n" + json.dumps(c) + "\n</tool_call>" for c in calls
                )
                return self._body(payload, call_index, "Let me look that up.\n" + blocks,
                                  completions=True, finish_reason="stop")
            tool_calls = [
                {
                    "id": f"call_{call_index}_{i}",
                    "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                }
                for i, c in enumerate(calls)
            ]
            return self._body(payload, call_index, None, tool_calls=tool_calls,
                              finish_reason="tool_calls")

        total = sum(float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", tool_results))
        total = int(total) if total == int(total) else total
        return self._body(payload, call_index, f"Based on the tools, the answer is {total}.",
                          completions=completions)

    def _body(self, payload, call_index, text, tool_calls=None, finish_reason="stop",
              completions=False):
        if completions or self.path == "/v1/completions":
            return json.dumps(
                {
                    "id": f"cmpl-{call_index}",
                    "object": "text_completion",
                    "model": payload.get("model", "mock"),
                    "choices": [
                        {"index": 0, "text": text or "", "finish_reason": finish_reason}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "_temperature": payload.get("temperature", 0.0),
                }
            ).encode()
        message = {"role": "assistant", "content": text}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return json.dumps(
            {
                "id": f"chatcmpl-{call_index}",
                "object": "chat.completion",
                "model": payload.get("model", "mock"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
                "_temperature": payload.get("temperature", 0.0),
            }
        ).encode()

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def mixed_reply(system: str, user: str) -> str:
    """Dispatch on the system prompt so one server can back a multi-task run."""
    low = system.lower()
    if "evaluator" in low or "1 to 10" in low or "rate" in low:
        return str(STATE["judge_score"])
    if "single letter" in low or "multiple choice" in low:
        return f"The answer is {STATE['letter']}) some option"
    if "python function" in low or "only the function code" in low:
        return "def solve(n):\n    # good code\n    return n"
    if "writing assistant" in low:
        return "A thoughtful written response about the topic."
    return f"Step by step.\n#### {solve(user)}"


def solve(question: str) -> str:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", question)]
    if not nums:
        return "0"
    total = sum(nums)
    return str(int(total)) if total == int(total) else str(total)


def main():
    global SEM
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--latency", type=float, default=1.0)
    ap.add_argument("--mode", default="solve")
    ap.add_argument("--fail-n", type=int, default=2)
    ap.add_argument("--judge-score", default="8")
    ap.add_argument("--letter", default="B")
    args = ap.parse_args()
    STATE.update(workers=args.workers, latency=args.latency, mode=args.mode, fail_n=args.fail_n,
                 judge_score=args.judge_score, letter=args.letter)
    SEM = threading.BoundedSemaphore(args.workers)
    server = Server(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"mock server on {args.port} workers={args.workers} latency={args.latency} mode={args.mode}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

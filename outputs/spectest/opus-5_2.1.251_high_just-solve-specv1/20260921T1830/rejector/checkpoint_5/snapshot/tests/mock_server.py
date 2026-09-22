#!/usr/bin/env python3
"""Mock OpenAI-compatible completions server used by the test suite.

Serves ``/v1/chat/completions`` and ``/v1/completions``. Models a server that
queues requests internally: it processes at most ``capacity`` requests at a
time, each taking ``latency`` seconds. Overall throughput therefore caps at
``capacity / latency`` requests per second, and a sequential client can never
exceed ``1 / latency``.

Prompt markers drive the behaviour; see the test suites. Agentic markers:

``TOOLS:<round>|<round>``   one line; a round is ``name:k=v,k=v;name:k=v``
``LOOP_TOOLS``              keep replaying the last round forever
``FINAL:<text>``            the final (post-tool) answer
``ECHO_PROMPT``             completions mode: reply with the rendered prompt
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
REQUESTS: list[dict] = []  # {"path": ..., "body": ...} for assertions
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


def text_completion(request: dict, text: str) -> dict:
    """A /v1/completions response: choices[].text, not choices[].message."""
    return {
        "id": "cmpl-mock",
        "object": "text_completion",
        "created": int(time.time()),
        "model": request.get("model", "mock"),
        "choices": [{"index": 0, "text": text, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call_completion(request: dict, calls: list[dict]) -> dict:
    """A chat response that only requests tools (content is null)."""
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.get("model", "mock"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"]),
                            },
                        }
                        for index, call in enumerate(calls, start=1)
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def parse_tool_rounds(text: str) -> list[list[dict]]:
    """``TOOLS:lookup:key=a;lookup:key=b|calculate:expression=1+2`` -> rounds."""
    marker = re.search(r"^TOOLS:(.*)$", text, re.M)
    if not marker:
        return []
    rounds: list[list[dict]] = []
    for chunk in marker.group(1).strip().split("|"):
        calls = []
        for spec in chunk.split(";"):
            spec = spec.strip()
            if not spec:
                continue
            name, _, argument_text = spec.partition(":")
            arguments = {}
            for pair in argument_text.split(","):
                if not pair.strip():
                    continue
                key, _, value = pair.partition("=")
                arguments[key.strip()] = value.strip()
            calls.append({"name": name.strip(), "arguments": arguments})
        if calls:
            rounds.append(calls)
    return rounds


def final_text(user: str) -> str | None:
    marker = re.search(r"^FINAL:(.*)$", user, re.M)
    return marker.group(1).strip().replace("\\n", "\n") if marker else None


def as_tool_call_text(calls: list[dict]) -> str:
    """Render tool calls the way a completions-mode model would emit them."""
    blocks = []
    for call in calls:
        body = json.dumps({"name": call["name"], "arguments": call["arguments"]})
        blocks.append(f"<tool_call>\n{body}\n</tool_call>")
    return "\n".join(blocks)


USER_MARKERS = (
    "<|im_start|>user\n",
    "<|start_header_id|>user<|end_header_id|>\n\n",
    "<|user|>\n",
    "[INST] ",
)
END_MARKERS = ("<|im_end|>", "<|eot_id|>", "</s>", " [/INST]")


def last_user_segment(prompt: str) -> str:
    """The final user turn of a rendered prompt, for marker lookups."""
    start = -1
    for marker in USER_MARKERS:
        found = prompt.rfind(marker)
        if found > start:
            start = found
            offset = found + len(marker)
    if start < 0:
        return prompt
    segment = prompt[offset:]
    ends = [segment.find(end) for end in END_MARKERS if segment.find(end) >= 0]
    return segment[: min(ends)] if ends else segment


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
        if self.path == "/requests":
            with STATE_LOCK:
                self._send(200, {"requests": REQUESTS})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        global INFLIGHT, MAX_INFLIGHT, TOTAL
        if self.path not in ("/v1/chat/completions", "/v1/completions"):
            self._send(404, {"error": {"message": "unknown route"}})
            return
        completions = self.path == "/v1/completions"

        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": {"message": "invalid JSON"}})
            return

        messages = request.get("messages", [])
        prompt = request.get("prompt") or ""
        user = ""
        system = ""
        if completions:
            user = last_user_segment(prompt)
            system = prompt
            # Rounds are counted from the tool results fed back into the prompt;
            # the prompt's tool documentation also mentions <tool_call>.
            tool_results_seen = prompt.count("<tool_response>")
            tool_rounds_done = None
        else:
            for message in messages:
                if message.get("role") == "user":
                    user = message.get("content", "")
                elif message.get("role") == "system":
                    system = message.get("content", "")
            tool_rounds_done = sum(
                1 for message in messages
                if message.get("role") == "assistant" and message.get("tool_calls")
            )

        def reply(content: str) -> None:
            self._send(200, text_completion(request, content) if completions
                       else completion(request, content))

        with STATE_LOCK:
            REQUESTS.append({"path": self.path, "body": request})
            del REQUESTS[:-200]
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
            reply(scores[min(nth - 1, len(scores) - 1)])
            return

        # ECHO_PROMPT hands the rendered prompt back, so tests can inspect it.
        if completions and "ECHO_PROMPT" in prompt:
            reply(prompt)
            return

        # Agentic rounds: emit tool calls until the configured rounds run out.
        rounds = parse_tool_rounds(user)
        if rounds and tool_rounds_done is None:
            tool_rounds_done = 0
            counted = 0
            for round_calls in rounds:
                if counted + len(round_calls) > tool_results_seen:
                    break
                counted += len(round_calls)
                tool_rounds_done += 1
        if rounds:
            calls = None
            if tool_rounds_done < len(rounds):
                calls = rounds[tool_rounds_done]
            elif "LOOP_TOOLS" in user:
                calls = rounds[-1]
            if calls is not None:
                if completions:
                    reply(as_tool_call_text(calls))
                else:
                    self._send(200, tool_call_completion(request, calls))
                return

        answer = final_text(user)
        if answer is not None:
            reply(answer)
            return

        # SAY:<text> replies verbatim (\n escapes become newlines).
        say = re.search(r"SAY:(.*)", user, re.S)
        if say:
            reply(say.group(1).replace("\\n", "\n"))
            return

        correct = solve(user)
        reject = re.search(r"REJECT(\d+)", user)
        if reject and nth <= int(reject.group(1)):
            content = f"Thinking about it.\n#### {int(float(correct)) + 100}"
        elif "NEVER" in user:
            content = "Thinking about it.\n#### 999999"
        else:
            content = f"Let me solve this step by step.\n{user.strip()}\n#### {correct}"

        reply(content)


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

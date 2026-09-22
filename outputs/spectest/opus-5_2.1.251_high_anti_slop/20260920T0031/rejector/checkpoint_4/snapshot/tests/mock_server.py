#!/usr/bin/env python3
"""Mock OpenAI-compatible server used to exercise the CLI end to end.

It processes a bounded number of requests at a time (so extra requests queue
rather than being rejected) and answers with the last number found in the
conversation, which lets `exact_match` + `last_number` evaluation be predicted.
It serves both `/v1/chat/completions` and `/v1/completions`, and when a request
offers tools it asks for `--tool-calls` of them before answering — so an agentic
loop takes a tool call and then a final answer.
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

#: Opening line of the tool section a completions prompt carries.
TOOL_INSTRUCTIONS = "You have access to the following tools:"
#: Role markers a tool result is rendered with by the built-in chat templates.
TOOL_RESULT_MARKERS = ("<|im_start|>tool", "<|start_header_id|>tool", "<|tool|>", "[TOOL_RESULTS]")


class Settings:
    """Server behaviour knobs shared by all handler threads."""

    def __init__(self, rpm: int, latency: float, fail_rate: float, accuracy: float, tool_calls: int = 1) -> None:
        self.latency = latency
        self.fail_rate = fail_rate
        self.accuracy = accuracy
        self.tool_calls = tool_calls
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
        choice = self._text_choice(body) if "prompt" in body else self._chat_choice(body)
        return {
            "id": "chatcmpl-mock",
            "model": body["model"],
            "choices": [{"index": 0, **choice}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def _chat_choice(self, body: dict) -> dict:
        """A native tool call until enough tools have answered, then the final answer."""
        messages = body["messages"]
        conversation = " ".join(message["content"] or "" for message in messages if message["role"] in ("user", "tool"))
        tools = body.get("tools") or []
        answered = sum(1 for message in messages if message["role"] == "tool")
        if tools and answered < self.settings.tool_calls:
            call = _tool_request(tools[0]["function"], conversation)
            function = {"name": call["name"], "arguments": json.dumps(call["arguments"])}
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_mock", "type": "function", "function": function}],
            }
            return {"message": message, "finish_reason": "tool_calls"}
        return {"message": {"role": "assistant", "content": self._answer(conversation)}, "finish_reason": "stop"}

    def _text_choice(self, body: dict) -> dict:
        """The same two steps written as text: a `<tool_call>` block, then the final answer."""
        prompt = body["prompt"]
        answered = sum(prompt.count(marker) for marker in TOOL_RESULT_MARKERS)
        if TOOL_INSTRUCTIONS in prompt and answered < self.settings.tool_calls:
            call = _tool_request(_prompt_function(prompt), prompt)
            return {"text": f"<tool_call>\n{json.dumps(call)}\n</tool_call>", "finish_reason": "tool_calls"}
        return {"text": self._answer(prompt), "finish_reason": "stop"}

    def _answer(self, conversation: str) -> str:
        """The last number in the conversation, made wrong for a `--accuracy` share of requests."""
        answer = _last_number(conversation)
        if random.random() >= self.settings.accuracy:
            answer = str(float(answer) + 1)
        return f"Working it out.\n#### {answer}"

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


def _last_number(text: str) -> str:
    numbers = NUMBER.findall(text)
    return numbers[-1] if numbers else "0"


def _tool_request(function: dict, conversation: str) -> dict:
    """The call the mock asks for: the first tool, keyed by the last number it has seen."""
    key = function["parameters"]["required"][0]
    return {"name": function["name"], "arguments": {key: _last_number(conversation)}}


def _prompt_function(prompt: str) -> dict:
    """The first tool definition described in a completions prompt."""
    return {
        "name": re.search(r'"name":\s*"([^"]+)"', prompt).group(1),
        "parameters": {"required": [re.search(r'"required":\s*\[\s*"([^"]+)"', prompt).group(1)]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rpm", type=int, default=60, help="requests per minute the server can process")
    parser.add_argument("--latency", type=float, default=1.0, help="seconds spent on each request")
    parser.add_argument("--fail-rate", type=float, default=0.0, help="fraction of requests answered with a 503")
    parser.add_argument("--accuracy", type=float, default=1.0, help="fraction of responses with the right answer")
    parser.add_argument("--tool-calls", type=int, default=1, help="tool calls asked for before the final answer")
    args = parser.parse_args()

    Handler.settings = Settings(args.rpm, args.latency, args.fail_rate, args.accuracy, args.tool_calls)
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"mock server on :{args.port} rpm={args.rpm} latency={args.latency}s", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

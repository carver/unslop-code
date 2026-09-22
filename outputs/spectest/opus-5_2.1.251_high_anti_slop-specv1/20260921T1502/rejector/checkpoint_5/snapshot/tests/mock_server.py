"""A stand in for the chat completions and completions APIs, used by the tests.

The server mimics the real one: requests are queued and served by a limited
number of internal workers, each spending `delay` seconds on a request. A
responder answers with text, with a list of tool calls, or with an HTTP status
to fail the request with; the endpoint the request arrived on decides how that
answer is shaped.
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
# that exact prompt, and returns response text, a list of
# `{"name": ..., "arguments": {...}}` tool calls, or an HTTP status to fail with.
Reply = str | int | list[dict]
Responder = Callable[[dict, int], Reply]

COMPLETIONS_PATH = "/v1/completions"


@dataclass
class MockAPI:
    """Shared state behind the request handler."""

    responder: Responder
    delay: float
    gate: threading.Semaphore
    lock: threading.Lock = field(default_factory=threading.Lock)
    calls: list[dict] = field(default_factory=list)
    prompt_calls: dict[str, int] = field(default_factory=dict)

    def serve(self, payload: dict) -> Reply:
        """Spend the configured service time, then decide what to answer."""
        with self.gate:
            sleep(self.delay)
            with self.lock:
                prompt = json.dumps(payload.get("messages") or payload["prompt"])
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
        self._send(200, _completion(self.path, payload["model"], reply))

    def _send(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:  # keep pytest output readable
        pass


def _completion(path: str, model: str, reply: str | list[dict]) -> dict:
    """One response body, shaped for the endpoint the request arrived on."""
    finish_reason = "tool_calls" if isinstance(reply, list) else "stop"
    answer = {"text": _text(reply)} if path == COMPLETIONS_PATH else {"message": _message(reply)}
    return {
        "id": "chatcmpl-mock",
        "model": model,
        "choices": [{"index": 0, **answer, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _text(reply: str | list[dict]) -> str:
    """Tool calls reach a completions client as blocks inside the response text."""
    if not isinstance(reply, list):
        return reply
    return "\n".join(f"<tool_call>\n{json.dumps(call)}\n</tool_call>" for call in reply)


def _message(reply: str | list[dict]) -> dict:
    if not isinstance(reply, list):
        return {"role": "assistant", "content": reply}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{number}",
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
            }
            for number, call in enumerate(reply)
        ],
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


def _demo_responder(wrong_first: int, score: int) -> Responder:
    """Add up the numbers in the prompt, after `wrong_first` deliberately wrong answers.

    Summing is enough to "solve" the bundled examples, and the wrong answers make
    the rejection sampling scheme visibly retry. Judge prompts, recognised by the
    `Score:` ending of the bundled one, are answered with a fixed `score` instead.
    A chat request that offers tools is answered with one call to the first of
    them before the sum, so an agentic run makes a full round trip.
    """

    def respond(payload: dict, call: int) -> Reply:
        prompt = _last_turn(payload)
        if "Score:" in prompt:
            return str(score)
        tool_call = _demo_tool_call(payload)
        if tool_call is not None:
            return tool_call
        numbers = re.findall(r"-?\d+", prompt)
        total = sum(int(number) for number in numbers) if call > wrong_first else 0
        return f"Let me work through it step by step.\n#### {total}"

    return respond


def _last_turn(payload: dict) -> str:
    """The text of the last thing the caller said, whichever endpoint it used."""
    if "prompt" in payload:
        return payload["prompt"]
    return payload["messages"][-1]["content"]


def _demo_tool_call(payload: dict) -> list[dict] | None:
    """Call the first offered tool with the backquoted part of the question as its arguments.

    The questions of the bundled agentic example end on the database key or the
    snippet their tool should be given, so that is the argument worth sending.
    """
    tools = payload.get("tools")
    if not tools or any(message["role"] == "tool" for message in payload["messages"]):
        return None
    function = tools[0]["function"]
    quoted = re.findall(r"`([^`]+)`", _last_turn(payload))
    argument = quoted[-1] if quoted else _last_turn(payload)
    required = function["parameters"].get("required", [])
    return [{"name": function["name"], "arguments": {name: argument for name in required}}]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the mock chat completions API.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--delay", type=float, default=0.5, help="service time per request")
    parser.add_argument("--capacity", type=int, default=8, help="requests served in parallel")
    parser.add_argument("--wrong-first", type=int, default=0, help="wrong answers per prompt")
    parser.add_argument("--score", type=int, default=8, help="score returned to judge prompts")
    options = parser.parse_args()
    responder = _demo_responder(options.wrong_first, options.score)
    url, _, _ = start_mock_server(responder, options.delay, options.capacity, options.port)
    print(f"mock API listening on {url}", flush=True)
    threading.Event().wait()

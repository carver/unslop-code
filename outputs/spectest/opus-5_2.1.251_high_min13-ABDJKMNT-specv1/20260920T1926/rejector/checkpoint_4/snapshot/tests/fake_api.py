"""A minimal OpenAI-compatible API server for tests.

Serves both `/v1/chat/completions` and `/v1/completions`, shaping each reply
to match the endpoint it arrived on.

The real server described by the spec "queues requests internally and spends
time processing each request", so this stand-in models capacity with a
semaphore of `slots` workers each taking `delay` seconds per request. That
makes a sequential client measurably slower than a concurrent one.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


@dataclass
class Reply:
    """What the fake server should do for one request.

    `tools` holds `{"name", "arguments"}` dicts; the handler renders them as
    native `tool_calls` on the chat endpoint and as `<tool_call>` text blocks
    on the completions endpoint, so one responder drives both modes.
    """

    content: str | None = "#### 42"
    status: int = 200
    finish_reason: str = "stop"
    prompt_tokens: int = 10
    completion_tokens: int = 20
    tools: tuple[dict, ...] = ()


# A responder maps (call_index, request_body) -> Reply.
Responder = Callable[[int, dict], Reply]


def call(name: str, **arguments) -> dict:
    """One tool call for `Reply.tools`."""
    return {"name": name, "arguments": arguments}


def conversation_text(body: dict) -> str:
    """Everything the request says, whichever endpoint shape it used."""
    if "prompt" in body:
        return body["prompt"]
    return "\n".join(str(message.get("content") or "") for message in body["messages"])


def assistant_turns(body: dict) -> int:
    """How many assistant turns the conversation already carries.

    Completions requests have no roles, so prior tool-call turns are counted
    by their rendered `</tool_call>` blocks, discounting the one the tool
    preamble shows as an example; a turn making several calls therefore
    counts as several. Chat requests must not use ICL here, whose
    demonstrations are assistant turns too.
    """
    if "prompt" in body:
        return max(body["prompt"].count("</tool_call>") - 1, 0)
    return sum(1 for message in body["messages"] if message["role"] == "assistant")


def turns(replies: list[Reply]) -> Responder:
    """Responder that walks `replies` by conversation depth, not call order.

    Rows run concurrently, so a call-index script would interleave across
    rows; keying on the conversation itself gives every row the same script.
    """
    return lambda index, body: replies[min(assistant_turns(body), len(replies) - 1)]


def after(marker: str, before: Reply, then: Reply) -> Responder:
    """Answer `before` until `marker` shows up in the conversation, then `then`."""
    return lambda index, body: then if marker in conversation_text(body) else before


def always(content: str, **kwargs) -> Responder:
    """Responder that answers every request identically."""
    return lambda index, body: Reply(content=content, **kwargs)


def sequence(replies: list[Reply]) -> Responder:
    """Responder that walks a fixed script, repeating the last entry."""
    return lambda index, body: replies[min(index, len(replies) - 1)]


def by_question(mapping: dict[str, Reply], default: Reply | None = None) -> Responder:
    """Responder keyed on the rendered user message, for order-safety checks."""

    def respond(index: int, body: dict) -> Reply:
        user = body["messages"][-1]["content"]
        return mapping.get(user, default or Reply(content="unmapped"))

    return respond


def by_system(mapping: dict[str, Reply], default: Reply | None = None) -> Responder:
    """Responder keyed on the system message, to tell judge calls from generation calls."""

    def respond(index: int, body: dict) -> Reply:
        system = body["messages"][0]["content"]
        return mapping.get(system, default or Reply(content="unmapped"))

    return respond


@dataclass
class FakeAPI:
    """Threaded fake API; use as a context manager and read `url`."""

    responder: Responder = field(default_factory=lambda: always("#### 42"))
    slots: int = 8
    delay: float = 0.05

    def __post_init__(self) -> None:
        self.requests: list[dict] = []
        self.paths: list[str] = []
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(self.slots)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def next_reply(self, body: dict) -> Reply:
        with self._lock:
            index = len(self.requests)
            self.requests.append(body)
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        return self.responder(index, body)

    def finish_one(self) -> None:
        with self._lock:
            self._active -= 1

    def serve(self, body: dict) -> Reply:
        """Apply capacity limits and processing time, then answer."""
        reply = self.next_reply(body)
        with self._slots:
            time.sleep(self.delay)
        self.finish_one()
        return reply

    def __enter__(self) -> "FakeAPI":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()


def _make_handler(api: FakeAPI):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            api.paths.append(self.path)
            reply = api.serve(body)
            if reply.status != 200:
                self._send(reply.status, {"error": {"message": "boom"}})
                return
            shape = _text_choice if self.path.endswith("/v1/completions") else _chat_choice
            self._send(200, _completion(body.get("model", "unknown"), reply, shape))

        def _send(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args) -> None:
            pass

    return Handler


def _completion(model: str, reply: Reply, shape) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [{"index": 0, **shape(reply), "finish_reason": _finish(reply)}],
        "usage": {
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "total_tokens": reply.prompt_tokens + reply.completion_tokens,
        },
    }


def _finish(reply: Reply) -> str:
    return "tool_calls" if reply.tools else reply.finish_reason


def _chat_choice(reply: Reply) -> dict:
    """The `choices[].message` shape, with native OpenAI tool calls."""
    message: dict = {"role": "assistant", "content": reply.content}
    if reply.tools:
        message["tool_calls"] = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": item["name"], "arguments": json.dumps(item["arguments"])},
            }
            for index, item in enumerate(reply.tools)
        ]
    return {"message": message}


def _text_choice(reply: Reply) -> dict:
    """The `choices[].text` shape, with tool calls as `<tool_call>` blocks."""
    blocks = [f"<tool_call>\n{json.dumps(item)}\n</tool_call>" for item in reply.tools]
    return {"text": "\n".join(blocks) if blocks else (reply.content or "")}

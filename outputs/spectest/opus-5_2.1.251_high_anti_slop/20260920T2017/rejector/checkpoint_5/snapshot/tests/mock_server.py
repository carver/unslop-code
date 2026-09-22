#!/usr/bin/env python3
"""Mock OpenAI-compatible server used to exercise the CLI.

It emulates a backend with a fixed number of workers, each taking `--delay`
seconds per request, so its capacity is `workers / delay * 60` requests per
minute. Requests beyond that queue up inside the server. Both
`/v1/chat/completions` and `/v1/completions` are served, each only accepting
the request body that belongs on it.

The reply echoes the `ANSWER=<value>` marker found in the user prompt, which
lets tests control whether a response passes evaluation. A prompt holding a
`JSON=<object>` marker is answered with that object instead, so tests can drive
structured output validation; an attempt that is not meant to pass answers with
prose, which no schema accepts. When the request
carries in-context examples, the reply also echoes an `ICL=<count>:<first
assistant turn>` line, so tests can see which setup was prompted with.

A prompt holding `TOOL=<name>:<json arguments>` markers drives the agentic
loop: the server asks for those calls for the first `--tool-rounds` rounds,
then answers with a `RESULTS=` line echoing what the tools sent back.
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

#: Markers a row plants in its question; both stop before any template markup.
ANSWER_MARKER = re.compile(r"ANSWER=([\w.-]+)")
JSON_MARKER = re.compile(r"JSON=(\{.*\})")
TOOL_MARKER = re.compile(r"TOOL=(\w+):(\{.*?\})")
CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


class Conversation:
    """One request's conversation, read from whichever endpoint it arrived on."""

    def __init__(self, user: str, examples: list[str], tool_results: list[str], rounds: int):
        self.user = user
        self.examples = examples
        self.tool_results = tool_results
        self.rounds = rounds


def from_messages(messages: list[dict]) -> Conversation:
    """A chat request: roles are explicit, so every part is read off directly.

    The row's own question is the last user turn, which stays put as the
    agentic loop appends tool calls and their results after it.
    """
    users = [m["content"] for m in messages if m["role"] == "user"]
    return Conversation(
        user=users[-1],
        examples=[m["content"] for m in messages if m["role"] == "assistant" and m.get("content")],
        tool_results=[m["content"] for m in messages if m["role"] == "tool"],
        rounds=sum(1 for m in messages if m.get("tool_calls")),
    )


def from_prompt(prompt: str) -> Conversation:
    """A completions request: one string, so the rounds are counted from its blocks.

    Only blocks naming a tool the row asked for count: the rendered tool
    instructions carry an example block of their own. Everything after the last
    block is the result that came back, which is enough for a test to see that
    results reached the model.
    """
    requested = TOOL_MARKER.findall(prompt)
    names = {name for name, _ in requested}
    made = [call for call in map(json.loads, CALL_BLOCK.findall(prompt)) if call["name"] in names]
    _, _, tail = prompt.rpartition("</tool_call>")
    return Conversation(
        user=prompt,
        examples=[],
        tool_results=[tail] if made else [],
        rounds=len(made) // len(requested) if requested else 0,
    )


class Backend:
    """Shared state: worker capacity, per-prompt attempt counts, error injection."""

    def __init__(self, workers: int, delay: float, pass_after: int, pass_every: int,
                 fail_500: int, always_500: bool, tool_rounds: int,
                 prompt_tokens: int, completion_tokens: int):
        self.slots = threading.Semaphore(workers)
        self.delay = delay
        self.pass_after = pass_after
        self.pass_every = pass_every
        self.always_500 = always_500
        self.tool_rounds = tool_rounds
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self._lock = threading.Lock()
        self._remaining_500 = fail_500
        self._calls = itertools.count(1)
        self._attempts: dict[str, int] = defaultdict(int)

    def handle(self, conversation: Conversation, chat: bool) -> tuple[int, dict]:
        with self._lock:
            call = next(self._calls)
            self._attempts[conversation.user] += 1
            attempt = self._attempts[conversation.user]
            inject_500 = self.always_500 or self._remaining_500 > 0
            if self._remaining_500 > 0:
                self._remaining_500 -= 1

        with self.slots:
            time.sleep(self.delay)

        if inject_500:
            return 500, {"error": "backend overloaded"}
        requested = TOOL_MARKER.findall(conversation.user)
        if requested and conversation.rounds < self.tool_rounds:
            return 200, self._envelope(call, self._tool_choice(requested, chat))
        return 200, self._envelope(call, self._answer_choice(conversation, attempt, chat))

    def _tool_choice(self, requested: list[tuple[str, str]], chat: bool) -> dict:
        """Ask for every tool the prompt named, in the shape the endpoint uses."""
        if not chat:
            blocks = "\n".join(
                f'<tool_call>\n{{"name": "{name}", "arguments": {arguments}}}\n</tool_call>'
                for name, arguments in requested
            )
            return {"text": blocks, "finish_reason": "tool_calls"}
        calls = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
            for index, (name, arguments) in enumerate(requested, start=1)
        ]
        message = {"role": "assistant", "content": None, "tool_calls": calls}
        return {"index": 0, "message": message, "finish_reason": "tool_calls"}

    def _answer_choice(self, conversation: Conversation, attempt: int, chat: bool) -> dict:
        answer = ANSWER_MARKER.search(conversation.user)
        passes = attempt >= self.pass_after and attempt % self.pass_every == 0
        value = answer.group(1) if answer and passes else "0"
        icl = f"\nICL={len(conversation.examples)}:{conversation.examples[0]}" \
            if conversation.examples else ""
        results = f"\nRESULTS={'|'.join(conversation.tool_results)}" \
            if conversation.tool_results else ""
        text = f"Working it out.{icl}{results}\n#### {value}"
        structured = JSON_MARKER.search(conversation.user)
        if structured and passes:
            text = structured.group(1)
        if not chat:
            return {"text": text, "finish_reason": "stop"}
        return {
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }

    def _envelope(self, call: int, choice: dict) -> dict:
        return {
            "id": f"chatcmpl-{call}",
            "model": "mock-model",
            "choices": [choice],
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
            },
        }


class QueueingServer(ThreadingHTTPServer):
    """A deep listen backlog: connections wait rather than being refused."""

    request_queue_size = 256
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    backend: Backend

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        chat = "messages" in body
        # Each endpoint takes only the body that belongs on it, so a test can
        # tell which one the client chose.
        if self.path != ("/v1/chat/completions" if chat else "/v1/completions"):
            status, payload = 404, {"error": f"{self.path} does not take this request"}
        else:
            conversation = from_messages(body["messages"]) if chat else from_prompt(body["prompt"])
            status, payload = self.backend.handle(conversation, chat)
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
    parser.add_argument("--tool-rounds", type=int, default=1,
                        help="rounds of tool calls before a final answer")
    parser.add_argument("--prompt-tokens", type=int, default=10, help="usage reported per call")
    parser.add_argument("--completion-tokens", type=int, default=5, help="usage reported per call")
    args = parser.parse_args()

    Handler.backend = Backend(args.workers, args.delay, args.pass_after, args.pass_every,
                              args.fail_500, args.always_500, args.tool_rounds,
                              args.prompt_tokens, args.completion_tokens)
    server = QueueingServer(("127.0.0.1", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

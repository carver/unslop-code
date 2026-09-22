"""Mock OpenAI-compatible server used by the test suite.

It serves both ``/v1/chat/completions`` and ``/v1/completions``. The reply
echoes the last user message (or the whole rendered prompt in completions
mode), the temperature, and how many messages the request carried, so tests can
see the in-context examples that were sent. Each request occupies one of
``--capacity`` service slots for ``--latency`` seconds; extra requests queue,
mirroring a server that never rate-limits but does take time. A request whose
system message mentions "judge" is answered with ``--judge-score`` alone, so
llm_judge evaluations get a scoreable reply.

Tool calls are driven by the prompt: a ``CALL <tool> <json args>`` marker in the
question makes the server ask for that tool once per conversation, or on every
request with ``--always-call-tools``. Once a tool result has come back, the
final answer repeats the last result, so tests can see it reached the model.
With ``--answer-only`` the reply is the answer alone, so a test can hand the
client an exact response such as a JSON document. A ``GET /peak`` reports the
most requests the server ever had in flight at once.
Prints the bound port on stdout once it is listening.
"""

import argparse
import json
import re
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: The marker a test question carries to make the server request a tool call.
CALL_RE = re.compile(r"CALL (\w+) (\{.*?\})")
#: How a completions-mode client hands a tool result back in the prompt.
TOOL_RESPONSE_RE = re.compile(r"<tool_response>\s*([^<]*?)\s*</tool_response>")


class _State:
    """Shared request bookkeeping for the handler threads."""

    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.slots = threading.BoundedSemaphore(options.capacity)
        self.lock = threading.Lock()
        self.attempts_per_prompt: Counter[str] = Counter()
        self.in_flight = 0
        self.peak_in_flight = 0

    def enter(self) -> None:
        """Note one more request in flight, remembering the highest count seen."""
        with self.lock:
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)

    def leave(self) -> None:
        with self.lock:
            self.in_flight -= 1

    def next_answer(self, prompt: str) -> str:
        """Answer a prompt's ``attempt``-th call, wrongly while that attempt has to fail."""
        with self.lock:
            self.attempts_per_prompt[prompt] += 1
            attempt = self.attempts_per_prompt[prompt]
        if self.options.pass_every:
            passes = attempt % self.options.pass_every == 0
        else:
            passes = attempt > self.options.pass_after
        return self.options.answer if passes else self.options.wrong_answer

    def requested_calls(self, prompt: str, results: list[str]) -> list[tuple[str, dict]]:
        """The calls a prompt asks for, once per conversation unless told to repeat them."""
        if results and not self.options.always_call_tools:
            return []
        return [(name, json.loads(args)) for name, args in CALL_RE.findall(prompt)]


class _Server(ThreadingHTTPServer):
    """Threading server with a listen backlog deep enough for a burst of clients."""

    request_queue_size = 512


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _State

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        options = self.state.options
        if options.always_fail:
            self._respond(503, {"error": "service unavailable"})
            return

        self.state.enter()
        try:
            with self.state.slots:
                time.sleep(options.latency)
        finally:
            self.state.leave()
        payload = self._text_reply(body) if "prompt" in body else self._chat_reply(body)
        self._respond(200, payload)

    def do_GET(self) -> None:
        """Report the peak number of requests served concurrently."""
        self._respond(200, {"peak": self.state.peak_in_flight})

    def _chat_reply(self, body: dict) -> dict:
        """Answer a chat request with either tool calls or a final assistant message."""
        messages = body["messages"]
        prompt = [message["content"] for message in messages if message["role"] == "user"][-1]
        results = [message["content"] for message in messages if message["role"] == "tool"]
        calls = self.state.requested_calls(prompt, results)
        if calls:
            message = {"role": "assistant", "content": None, "tool_calls": _chat_tool_calls(calls)}
            return _payload({"message": message}, "tool_calls", prompt, "")
        content = self._content(body, prompt, results)
        return _payload({"message": {"role": "assistant", "content": content}}, "stop", prompt, content)

    def _text_reply(self, body: dict) -> dict:
        """Answer a completions request, reading the conversation back out of the prompt."""
        prompt = body["prompt"]
        results = TOOL_RESPONSE_RE.findall(prompt)
        calls = self.state.requested_calls(prompt, results)
        if calls:
            return _payload({"text": _tool_call_blocks(calls)}, "tool_calls", prompt, "")
        answer = results[-1] if results else self.state.next_answer(prompt)
        text = f"echo: {_defanged(prompt)}\n#### {answer}"
        return _payload({"text": text}, "stop", prompt, text)

    def _content(self, body: dict, prompt: str, results: list[str]) -> str:
        """Echo the prompt with an answer appended, or act as a judge when asked to."""
        system = " ".join(m["content"] for m in body["messages"] if m["role"] == "system")
        if "judge" in system.lower():
            return self.state.options.judge_score
        turns = len(body["messages"])
        answer = results[-1] if results else self.state.next_answer(prompt)
        if self.state.options.answer_only:
            return answer
        return f"echo: {prompt} temp={body['temperature']} turns={turns}\n#### {answer}"

    def _respond(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr access log."""


def _payload(choice: dict, finish_reason: str, prompt: str, content: str) -> dict:
    """Wrap one chat message or completion text in the usual response envelope."""
    prompt_tokens, completion_tokens = len(prompt.split()), len(content.split())
    return {
        "id": "cmpl-mock",
        "choices": [{"index": 0, **choice, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _defanged(prompt: str) -> str:
    """Quote the prompt without its tool-call markers, which the client would read back as calls."""
    return prompt.replace("<tool_call>", "(tool_call)")


def _chat_tool_calls(calls: list[tuple[str, dict]]) -> list[dict]:
    return [
        {
            "id": f"call_{index}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
        for index, (name, args) in enumerate(calls)
    ]


def _tool_call_blocks(calls: list[tuple[str, dict]]) -> str:
    """The same calls as the text blocks a completions-mode model would emit."""
    return "\n".join(
        "<tool_call>\n" + json.dumps({"name": name, "arguments": args}) + "\n</tool_call>"
        for name, args in calls
    )


def parse_options(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--latency", type=float, default=0.05, help="seconds spent serving one request")
    parser.add_argument("--capacity", type=int, default=8, help="requests served concurrently")
    parser.add_argument("--answer", default="8", help="answer returned once a prompt is allowed to pass")
    parser.add_argument("--wrong-answer", default="-1", help="answer returned while a prompt must fail")
    parser.add_argument("--pass-after", type=int, default=0, help="failing responses per prompt before passing")
    parser.add_argument("--pass-every", type=int, default=0, help="pass only every Nth call of a prompt")
    parser.add_argument("--judge-score", default="8", help="reply sent to judge prompts")
    parser.add_argument("--always-fail", action="store_true", help="reply 503 to every request")
    parser.add_argument(
        "--answer-only",
        action="store_true",
        help="reply with the answer alone, without echoing the prompt",
    )
    parser.add_argument(
        "--always-call-tools",
        action="store_true",
        help="request the prompt's tool calls again on every request, never answering",
    )
    return parser.parse_args(argv)


def main() -> None:
    options = parse_options()
    handler = type("_BoundHandler", (_Handler,), {"state": _State(options)})
    server = _Server(("127.0.0.1", options.port), handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Mock OpenAI-compatible chat completions server used by the test suite.

The reply echoes the last user message, the temperature, and how many messages
the request carried, so tests can see the in-context examples that were sent.
Each request occupies one of ``--capacity`` service slots for ``--latency``
seconds; extra requests queue, mirroring a server that never rate-limits but
does take time. A request whose system message mentions "judge" is answered
with ``--judge-score`` alone, so llm_judge evaluations get a scoreable reply.
Prints the bound port on stdout once it is listening.
"""

import argparse
import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _State:
    """Shared request bookkeeping for the handler threads."""

    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.slots = threading.BoundedSemaphore(options.capacity)
        self.lock = threading.Lock()
        self.attempts_per_prompt: Counter[str] = Counter()

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

        with self.state.slots:
            time.sleep(options.latency)
        self._respond(200, self._completion(body))

    def _completion(self, body: dict) -> dict:
        prompt = [message["content"] for message in body["messages"] if message["role"] == "user"][-1]
        content = self._content(body, prompt)
        return {
            "id": "chatcmpl-mock",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": len(content.split()), "total_tokens": 1},
        }

    def _content(self, body: dict, prompt: str) -> str:
        """Echo the prompt with an answer appended, or act as a judge when asked to."""
        system = " ".join(m["content"] for m in body["messages"] if m["role"] == "system")
        if "judge" in system.lower():
            return self.state.options.judge_score
        turns = len(body["messages"])
        return f"echo: {prompt} temp={body['temperature']} turns={turns}\n#### {self.state.next_answer(prompt)}"

    def _respond(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr access log."""


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
    return parser.parse_args(argv)


def main() -> None:
    options = parse_options()
    handler = type("_BoundHandler", (_Handler,), {"state": _State(options)})
    server = _Server(("127.0.0.1", options.port), handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

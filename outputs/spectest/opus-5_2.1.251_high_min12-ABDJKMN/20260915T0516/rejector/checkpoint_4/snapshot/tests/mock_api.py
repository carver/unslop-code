"""A mock OpenAI-compatible chat-completions server for the test suite.

The real server "queues requests internally and spends time processing each
request" and never returns rate-limit errors, so the mock models capacity as
`capacity_rpm` concurrent-slots x `service_seconds` of work per request.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def chat_response(content, prompt_tokens=45, completion_tokens=120,
                  finish_reason="stop", model="gpt-4"):
    """A standard OpenAI-style chat completion body."""
    return {
        "id": "chatcmpl-abc123",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class MockAPI:
    """Serves POST /v1/chat/completions.

    `responder(payload, call_index) -> (status, body_dict_or_text)`.
    Every request is recorded in `.calls` (list of request payloads) and
    `.paths`.
    """

    def __init__(self, responder=None, service_seconds=0.0, capacity_rpm=None):
        self.responder = responder or (lambda payload, i: (200, chat_response("#### 42")))
        self.service_seconds = service_seconds
        self.calls = []
        self.paths = []
        self._lock = threading.Lock()
        self._concurrent = 0
        self.max_concurrent = 0
        if capacity_rpm is None:
            self._slots = None
        else:
            slots = max(1, int(round(capacity_rpm * service_seconds / 60.0)))
            self._slots = threading.Semaphore(slots)
        self._server = None
        self._thread = None

    # -- lifecycle -----------------------------------------------------
    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {"_raw": raw.decode("utf-8", "replace")}
                with outer._lock:
                    index = len(outer.calls)
                    outer.calls.append(payload)
                    outer.paths.append(self.path)
                    outer._concurrent += 1
                    outer.max_concurrent = max(outer.max_concurrent, outer._concurrent)
                try:
                    if outer._slots is not None:
                        outer._slots.acquire()
                        try:
                            time.sleep(outer.service_seconds)
                        finally:
                            outer._slots.release()
                    elif outer.service_seconds:
                        time.sleep(outer.service_seconds)
                    status, body = outer.responder(payload, index)
                finally:
                    with outer._lock:
                        outer._concurrent -= 1
                if not isinstance(body, (str, bytes)):
                    body = json.dumps(body)
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- accessors -----------------------------------------------------
    @property
    def url(self):
        host, port = self._server.server_address[:2]
        return "http://%s:%d" % (host, port)

    @property
    def call_count(self):
        with self._lock:
            return len(self.calls)


# -- ready-made responders ---------------------------------------------

def always(content, **kw):
    """Always answer 200 with the same content."""
    return lambda payload, i: (200, chat_response(content, **kw))


def sequence(contents, **kw):
    """Answer with contents[i] per global call index; last value repeats."""
    def responder(payload, i):
        item = contents[i] if i < len(contents) else contents[-1]
        if isinstance(item, int):          # a bare status code, e.g. 500
            return item, {"error": "boom"}
        return 200, chat_response(item, **kw)
    return responder


def per_question(mapping, default="no answer", **kw):
    """Answer based on the rendered user message content."""
    def responder(payload, i):
        user = ""
        for m in payload.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        for key, value in mapping.items():
            if key in user:
                return 200, chat_response(value, **kw)
        return 200, chat_response(default, **kw)
    return responder


def status(code, times=None, then=None):
    """Return `code` for the first `times` calls (or always), then `then`."""
    then = then or always("#### 42")
    def responder(payload, i):
        if times is None or i < times:
            return code, {"error": {"message": "server error"}}
        return then(payload, i)
    return responder


def message_text(payload, role=None):
    """All message contents in a request payload, joined (optionally by role)."""
    parts = []
    for message in payload.get("messages", []):
        if role is None or message.get("role") == role:
            parts.append(message.get("content", ""))
    return "\n".join(parts)


def by_text(rules, default="no answer", **kw):
    """Answer by the first needle found anywhere in the request's messages.

    `rules` is a list of (needle, content). Used to tell a generation request
    apart from its `llm_judge` follow-up, which carries the judge prompt.
    """
    def responder(payload, i):
        text = message_text(payload)
        for needle, content in rules:
            if needle in text:
                if isinstance(content, int):
                    return content, {"error": "boom"}
                return 200, chat_response(content, **kw)
        return 200, chat_response(default, **kw)
    return responder


def by_model(mapping, default="no answer", **kw):
    """Answer based on the `model` field of the request payload."""
    def responder(payload, i):
        content = mapping.get(payload.get("model"), default)
        return 200, chat_response(content, model=payload.get("model"), **kw)
    return responder


# -- part 4: agentic + completions bodies -------------------------------

def completion_response(text, prompt_tokens=45, completion_tokens=120,
                        finish_reason="stop", model="gpt-4"):
    """A standard OpenAI-style *text* completion body (`choices[].text`)."""
    return {
        "id": "cmpl-abc123",
        "model": model,
        "choices": [
            {"index": 0, "text": text, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call_response(calls, prompt_tokens=45, completion_tokens=120,
                       finish_reason="tool_calls", model="gpt-4", content=None):
    """A chat body whose assistant message carries OpenAI-shaped tool calls.

    `calls` is a list of (name, args); args may be a dict (serialised to the
    JSON string the wire format uses) or a raw string.
    """
    tool_calls = []
    for index, (name, args) in enumerate(calls):
        arguments = args if isinstance(args, str) else json.dumps(args)
        tool_calls.append({
            "id": "call_%s%d" % (name, index),
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        })
    return {
        "id": "chatcmpl-abc123",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content,
                            "tool_calls": tool_calls},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call_text(calls):
    """The completions-mode text form of the same tool calls."""
    blocks = []
    for name, args in calls:
        blocks.append('<tool_call>\n%s\n</tool_call>'
                      % json.dumps({"name": name, "arguments": args}))
    return "\n".join(blocks)


ASSISTANT_MARKERS = ("<|im_start|>assistant",
                     "<|start_header_id|>assistant<|end_header_id|>",
                     "<|assistant|>", "[/INST]")


def prompt_rounds(prompt):
    """How many assistant turns a rendered prompt already contains.

    The trailing generation marker is not a completed turn, so it is not
    counted. Only valid for prompts without ICL assistant turns.
    """
    for marker in ASSISTANT_MARKERS:
        count = prompt.count(marker)
        if count:
            return count - 1
    return 0


def tool_rounds(payload):
    """How many tool-call rounds this conversation has already been through."""
    if "prompt" in payload:
        return prompt_rounds(payload["prompt"])
    return sum(1 for m in payload.get("messages", []) if m.get("tool_calls"))


def agentic_turns(steps, **kw):
    """Reply per tool-call round, in either chat or completions mode.

    `steps[k]` is the reply for round k: a list of (tool, args) tool calls, or
    a string final answer. The last step repeats.
    """
    def responder(payload, i):
        index = tool_rounds(payload)
        step = steps[index] if index < len(steps) else steps[-1]
        completions = "prompt" in payload
        if isinstance(step, int):
            return step, {"error": "boom"}
        if isinstance(step, list):
            if completions:
                return 200, completion_response(tool_call_text(step), **kw)
            return 200, tool_call_response(step, **kw)
        if completions:
            return 200, completion_response(step, **kw)
        return 200, chat_response(step, **kw)
    return responder

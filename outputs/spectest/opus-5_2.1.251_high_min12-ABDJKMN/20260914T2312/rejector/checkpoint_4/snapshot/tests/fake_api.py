"""A scriptable, OpenAI-compatible fake chat-completions server for the tests.

The server records every request it receives (path, headers, parsed body,
arrival/return timestamps) and delegates the response to a `responder`
callable so each test can script status codes, content and latency.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Recorded:
    """One received HTTP request plus the response the server gave back."""

    def __init__(self, path, body, index):
        self.path = path
        self.body = body
        self.index = index
        self.started = time.time()
        self.finished = None
        self.status = None

    @property
    def messages(self):
        return self.body.get("messages", [])

    @property
    def user_content(self):
        for m in self.messages:
            if m.get("role") == "user":
                return m.get("content")
        return None

    @property
    def user_contents(self):
        return [m.get("content") for m in self.messages
                if m.get("role") == "user"]

    @property
    def assistant_contents(self):
        return [m.get("content") for m in self.messages
                if m.get("role") == "assistant"]

    @property
    def roles(self):
        return [m.get("role") for m in self.messages]

    @property
    def icl_marker(self):
        """First assistant turn: identifies the ICL setup in tests."""
        contents = self.assistant_contents
        return contents[0] if contents else None

    @property
    def is_completions(self):
        return "prompt" in self.body

    @property
    def prompt(self):
        """The rendered prompt string of a /v1/completions request."""
        return self.body.get("prompt")

    @property
    def tools(self):
        """The `tools` field of a chat request (None when absent)."""
        return self.body.get("tools")

    @property
    def tool_names(self):
        return [t.get("function", {}).get("name") for t in (self.tools or [])]

    @property
    def tool_messages(self):
        return [m for m in self.messages if m.get("role") == "tool"]

    # Role markers a rendered template uses for a tool result, one per
    # built-in template.
    TOOL_MARKERS = ("<|im_start|>tool",
                    "<|start_header_id|>tool<|end_header_id|>",
                    "<|tool|>", "[TOOL_RESULTS]")

    @property
    def turn_index(self):
        """How many tool turns the conversation already contains.

        Chat mode counts assistant tool-call messages; completions mode counts
        the tool-result blocks rendered into the prompt (a turn that made
        several calls therefore counts once per call -- `agentic()` clamps the
        index to the end of the script, so scripts stay readable).
        """
        if self.is_completions:
            prompt = self.prompt or ""
            return sum(prompt.count(m) for m in self.TOOL_MARKERS)
        return sum(1 for m in self.messages if m.get("tool_calls"))

    @property
    def row_key(self):
        """A stable per-input-row key: the first user content of the request."""
        if self.is_completions:
            return self.prompt
        return self.user_content

    @property
    def system_content(self):
        for m in self.messages:
            if m.get("role") == "system":
                return m.get("content")
        return None


def completion(content, prompt_tokens=45, completion_tokens=120,
               finish_reason="stop", cid="chatcmpl-abc123"):
    """A standard OpenAI-style chat completion payload."""
    return {
        "id": cid,
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


# --------------------------------------------------------------------------
# Responder helpers.  A responder is  f(rec) -> (status:int, payload:dict|str)
# --------------------------------------------------------------------------

def always(content, **kw):
    """Every request gets the same response body."""
    def responder(rec):
        return 200, completion(content, **kw)
    return responder


def echo_user():
    """Response content is the rendered user prompt (handy for prompt tests)."""
    def responder(rec):
        return 200, completion(rec.user_content)
    return responder


def sequence(items):
    """Respond from a list, indexed by global call order.

    Each item is either a string (200 + that content) or an int (that HTTP
    status, with an error body).  The final item repeats if more calls arrive.
    """
    def responder(rec):
        item = items[rec.index] if rec.index < len(items) else items[-1]
        if isinstance(item, int):
            return item, {"error": {"message": "boom"}}
        return 200, completion(item)
    return responder


def per_prompt(mapping, default=None):
    """Pick a per-row `sequence`-style script keyed by user prompt content.

    The Nth call for a given prompt consumes the Nth item of its list.
    """
    counters = {}
    lock = threading.Lock()

    def responder(rec):
        key = rec.user_content
        items = mapping.get(key, default)
        assert items is not None, "no scripted response for prompt %r" % (key,)
        with lock:
            i = counters.get(key, 0)
            counters[key] = i + 1
        item = items[i] if i < len(items) else items[-1]
        if isinstance(item, int):
            return item, {"error": {"message": "boom"}}
        return 200, completion(item)
    return responder


def fail_times(n, then_content, status=500):
    """Return `status` for the first n calls, then a normal completion."""
    def responder(rec):
        if rec.index < n:
            return status, {"error": {"message": "server error"}}
        return 200, completion(then_content)
    return responder


class FakeAPI:
    """Threaded fake API server.  Use as a context manager."""

    def __init__(self, responder=None, latency=0.0, capacity=None):
        self.responder = responder or always("#### 8")
        self.latency = latency
        # `capacity` bounds how many requests may be *processed* at once; the
        # rest queue, mimicking the spec's "queues requests internally" server.
        self._slots = threading.Semaphore(capacity) if capacity else None
        self.requests = []
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_inflight = 0
        self._server = None
        self._thread = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # keep pytest output clean
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {"__raw__": raw.decode("utf-8", "replace")}
                status, payload = outer._handle(self.path, body)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.01},
                                        daemon=True)
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

    # -- request handling --------------------------------------------------
    def _handle(self, path, body):
        with self._lock:
            rec = Recorded(path, body, len(self.requests))
            self.requests.append(rec)
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            if self._slots is not None:
                self._slots.acquire()
            try:
                if self.latency:
                    time.sleep(self.latency)
                status, payload = self.responder(rec)
            finally:
                if self._slots is not None:
                    self._slots.release()
        finally:
            with self._lock:
                self._inflight -= 1
                rec.finished = time.time()
        rec.status = status
        return status, payload

    # -- inspection --------------------------------------------------------
    @property
    def url(self):
        host, port = self._server.server_address
        return "http://127.0.0.1:%d" % port

    @property
    def call_count(self):
        return len(self.requests)

    def bodies(self):
        return [r.body for r in self.requests]


def dispatch(predicate, when_true, when_false):
    """Route each request to one of two responders by `predicate(rec)`.

    Handy for llm_judge runs, where generation and judge calls hit the same
    server and must be scripted separately.
    """
    def responder(rec):
        return (when_true if predicate(rec) else when_false)(rec)
    return responder


# --------------------------------------------------------------------------
# Checkpoint 4: tool calls, agentic loops and /v1/completions payloads
# --------------------------------------------------------------------------

def tool_call(name, arguments, cid=None):
    """One OpenAI tool-call entry; `arguments` is JSON-encoded as the API does."""
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {"id": cid or ("call_%s" % name),
            "type": "function",
            "function": {"name": name, "arguments": arguments}}


def tool_completion(calls, prompt_tokens=45, completion_tokens=120,
                    finish_reason="tool_calls", cid="chatcmpl-tools"):
    """A chat completion whose message carries `tool_calls` and null content."""
    return {
        "id": cid,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None,
                            "tool_calls": list(calls)},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def text_completion(text, prompt_tokens=45, completion_tokens=120,
                    finish_reason="stop", cid="cmpl-abc123"):
    """A /v1/completions payload: `choices[].text`, not `choices[].message`."""
    return {
        "id": cid,
        "choices": [{"index": 0, "text": text, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call_text(name, arguments):
    """The completions-mode textual tool-call block."""
    return ('<tool_call>\n%s\n</tool_call>'
            % json.dumps({"name": name, "arguments": arguments}))


class Step:
    """One scripted model turn in an agentic script.

    `calls` is a list of (tool_name, args) pairs -> a tool-call turn;
    `text` -> a final answer turn.  `status` -> an HTTP error instead.
    """

    def __init__(self, text=None, calls=None, status=None, prompt_tokens=45,
                 completion_tokens=120, finish_reason=None):
        self.text = text
        self.calls = calls
        self.status = status
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.finish_reason = finish_reason

    def payload(self, completions):
        if self.calls is not None:
            if completions:
                text = "\n".join(tool_call_text(n, a) for n, a in self.calls)
                return text_completion(
                    text, self.prompt_tokens, self.completion_tokens,
                    self.finish_reason or "stop")
            return tool_completion(
                [tool_call(n, a) for n, a in self.calls],
                self.prompt_tokens, self.completion_tokens,
                self.finish_reason or "tool_calls")
        maker = text_completion if completions else completion
        return maker(self.text, self.prompt_tokens, self.completion_tokens,
                     self.finish_reason or "stop")


def calls(*pairs, **kw):
    """Shorthand: a tool-call turn, e.g. calls(("lookup", {"key": "x"}))."""
    return Step(calls=list(pairs), **kw)


def final(text, **kw):
    """Shorthand: a final-answer turn."""
    return Step(text=text, **kw)


def agentic(steps, per_row=None):
    """Script an agentic loop by *conversation position*, not call order.

    `steps` is the default list of Steps; `per_row` maps a row key (the first
    rendered user prompt, or for completions mode the whole prompt's first
    user block) to its own list.  The step used for a request is the number of
    tool-call turns already in the conversation, so concurrent rows stay
    independent without any shared counter.
    """
    def responder(rec):
        script = steps
        if per_row:
            for key, value in per_row.items():
                if rec.row_key is not None and key in rec.row_key:
                    script = value
                    break
        index = min(rec.turn_index, len(script) - 1)
        step = script[index]
        if step.status is not None:
            return step.status, {"error": {"message": "boom"}}
        return 200, step.payload(rec.is_completions)
    return responder

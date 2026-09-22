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

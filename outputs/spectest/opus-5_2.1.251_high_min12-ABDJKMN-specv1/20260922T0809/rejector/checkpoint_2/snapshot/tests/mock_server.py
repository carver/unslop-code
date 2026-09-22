"""A minimal OpenAI-compatible chat-completions server for the test-suite.

The server queues requests internally and spends time processing each request
(the `delay` argument), mirroring the server described in the spec. It never
returns rate-limit errors.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def completion(content, *, prompt_tokens=45, completion_tokens=120,
               finish_reason="stop", cid="chatcmpl-abc123"):
    """Build a standard OpenAI-style chat completion body."""
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


class MockAPI:
    """Threaded mock server.

    `responder(request_body, call_index) -> (status, body)` decides each reply.
    `body` may be a dict (sent as JSON) or a str (sent raw).
    """

    def __init__(self, responder, *, delay=0.0, capacity=None):
        self.responder = responder
        self.delay = delay
        # `capacity` simulates a server that can only process N requests at a
        # time; further requests queue.  None means unlimited parallelism.
        self._slots = threading.Semaphore(capacity) if capacity else None
        self.requests = []           # list of decoded request bodies
        self.paths = []              # list of request paths
        self.inflight = 0
        self.max_inflight = 0
        self._lock = threading.Lock()
        self._server = None
        self._thread = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # silence stderr noise
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = None
                with outer._lock:
                    outer.requests.append(body)
                    outer.paths.append(self.path)
                    index = len(outer.requests) - 1
                    outer.inflight += 1
                    outer.max_inflight = max(outer.max_inflight, outer.inflight)
                try:
                    if outer._slots:
                        outer._slots.acquire()
                    try:
                        if outer.delay:
                            time.sleep(outer.delay)
                        status, payload = outer.responder(body, index)
                    finally:
                        if outer._slots:
                            outer._slots.release()
                finally:
                    with outer._lock:
                        outer.inflight -= 1
                if isinstance(payload, (dict, list)):
                    data = json.dumps(payload).encode("utf-8")
                    ctype = "application/json"
                else:
                    data = str(payload).encode("utf-8")
                    ctype = "text/plain"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self.url

    @property
    def url(self):
        host, port = self._server.server_address[:2]
        return f"http://127.0.0.1:{port}"

    @property
    def call_count(self):
        with self._lock:
            return len(self.requests)

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            self._server = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False


def always(content, **kw):
    """Responder that always returns the same content."""
    body = completion(content, **kw)
    return lambda req, i: (200, body)


def sequence(items):
    """Responder driven by a list of `(status, body)` or plain content strings.

    The last entry repeats once the list is exhausted.
    """
    prepared = []
    for item in items:
        if isinstance(item, tuple):
            prepared.append(item)
        else:
            prepared.append((200, completion(item)))

    def responder(req, i):
        return prepared[min(i, len(prepared) - 1)]

    return responder


def per_prompt(mapping, default=None):
    """Responder keyed on the user message content."""
    def responder(req, i):
        user = ""
        for m in (req or {}).get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        value = mapping.get(user, default)
        if value is None:
            return 500, {"error": f"no scripted reply for {user!r}"}
        if isinstance(value, tuple):
            return value
        return 200, completion(value)

    return responder

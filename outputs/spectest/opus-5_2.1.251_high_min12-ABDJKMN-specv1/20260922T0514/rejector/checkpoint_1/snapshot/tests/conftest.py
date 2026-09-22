"""Shared fixtures: a mock OpenAI-compatible server and a CLI runner."""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
REJECTOR = REPO / "rejector.py"


def completion(content, *, model="gpt-4", prompt_tokens=30, completion_tokens=10,
               finish_reason="stop", cid="chatcmpl-abc123"):
    """A standard OpenAI-style chat completion payload."""
    return {
        "id": cid,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class MockAPI:
    """Threaded HTTP server standing in for the chat completions API.

    `responder(body, call_index) -> (status, payload)` decides each reply.
    `delay` simulates per-request processing time so concurrency is observable.
    """

    def __init__(self, responder, delay=0.0):
        self.responder = responder
        self.delay = delay
        self.lock = threading.Lock()
        self.requests = []
        self.inflight = 0
        self.max_inflight = 0
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep test output clean
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"__raw__": raw.decode("utf-8", "replace")}
                with mock.lock:
                    idx = len(mock.requests)
                    mock.requests.append({
                        "path": self.path,
                        "body": body,
                        "headers": dict(self.headers),
                        "t_start": time.time(),
                    })
                    mock.inflight += 1
                    mock.max_inflight = max(mock.max_inflight, mock.inflight)
                try:
                    if mock.delay:
                        time.sleep(mock.delay)
                    status, payload = mock.responder(body, idx)
                finally:
                    with mock.lock:
                        mock.inflight -= 1
                        mock.requests[idx]["t_end"] = time.time()
                data = json.dumps(payload).encode() if not isinstance(payload, (bytes, str)) \
                    else (payload.encode() if isinstance(payload, str) else payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_port

    @property
    def call_count(self):
        with self.lock:
            return len(self.requests)

    @property
    def bodies(self):
        with self.lock:
            return [r["body"] for r in self.requests]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    """Factory: api(responder, delay=0.0) -> MockAPI, torn down after the test."""
    made = []

    def _make(responder, delay=0.0):
        if not callable(responder):
            fixed = responder
            responder = lambda body, i: (200, fixed)
        m = MockAPI(responder, delay=delay)
        made.append(m)
        return m

    yield _make
    for m in made:
        m.stop()


@pytest.fixture
def echo_api(api):
    """Server that always answers with a fixed, passing-looking response."""
    return api(lambda body, i: (200, completion("2 + 3 = 5\n#### 5")))


def make_config(url, **over):
    """The spec's canonical greedy config, with overrides merged into task."""
    cfg = {
        "task": {
            "name": "math_solve",
            "api_url": url,
            "model": "gpt-4",
            "rpm": 60,
            "prompt": {
                "system": "Solve the math problem. Final answer after ####.",
                "user": "{question}",
            },
            "generation": {"scheme": "greedy", "max_tokens": 256},
            "evaluation": {
                "type": "exact_match",
                "answer_field": "answer",
                "extract": "last_number",
            },
            "output_field": "solution",
        }
    }
    for k, v in over.items():
        if v is None:
            cfg["task"].pop(k, None)
        else:
            cfg["task"][k] = v
    return cfg


class CliResult:
    def __init__(self, proc, out_path):
        self.proc = proc
        self.code = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr
        self.out_path = out_path

    @property
    def rows(self):
        text = self.out_path.read_text()
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    @property
    def summary(self):
        """The JSON summary object printed to stdout."""
        lines = [l for l in self.stdout.splitlines() if l.strip()]
        assert lines, "no summary on stdout; stderr=%s" % self.stderr
        return json.loads(lines[-1])


@pytest.fixture
def run_cli(tmp_path):
    counter = {"n": 0}

    def _run(config, rows, *, args=(), timeout=120, input_text=None, config_text=None):
        counter["n"] += 1
        tag = "case%d" % counter["n"]
        cfg_path = tmp_path / ("%s.yaml" % tag)
        if config_text is not None:
            cfg_path.write_text(config_text)
        else:
            cfg_path.write_text(yaml.safe_dump(config))
        in_path = tmp_path / ("%s.jsonl" % tag)
        if input_text is not None:
            in_path.write_text(input_text)
        else:
            in_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        out_path = tmp_path / ("%s.out.jsonl" % tag)
        cmd = [sys.executable, str(REJECTOR), "run",
               "--config", str(cfg_path), "--input", str(in_path),
               "--output", str(out_path)] + [str(a) for a in args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return CliResult(proc, out_path)

    return _run

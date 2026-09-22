"""Shared fixtures: a mock OpenAI-compatible server and a CLI runner."""
import json
import os
import signal
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


def tool_call_completion(calls, *, model="gpt-4", prompt_tokens=30,
                         completion_tokens=10, content=None,
                         finish_reason="tool_calls", cid="chatcmpl-tool"):
    """A chat completion whose assistant message carries `tool_calls`.

    `calls` is a list of {"name": ..., "arguments": <dict or JSON string>,
    optional "id"} in the spec's OpenAI shape.
    """
    tool_calls = []
    for index, call in enumerate(calls):
        arguments = call["arguments"]
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)
        tool_calls.append({
            "id": call.get("id", "call_%d" % index),
            "type": "function",
            "function": {"name": call["name"], "arguments": arguments},
        })
    return {
        "id": cid,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content,
                        "tool_calls": tool_calls},
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def text_completion(text, *, model="gpt-4", prompt_tokens=30,
                    completion_tokens=10, finish_reason="stop",
                    cid="cmpl-abc123"):
    """A `/v1/completions` style payload: `choices[].text`, not `.message`."""
    return {
        "id": cid,
        "model": model,
        "choices": [{"index": 0, "text": text, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call_text(calls):
    """The completions-mode `<tool_call>` block form from the spec."""
    return "\n".join(
        "<tool_call>\n%s\n</tool_call>"
        % json.dumps({"name": c["name"], "arguments": c["arguments"]})
        for c in calls)


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

    def _run(config, rows, *, args=(), timeout=120, input_text=None,
             config_text=None, files=None):
        counter["n"] += 1
        tag = "case%d" % counter["n"]
        cfg_path = tmp_path / ("%s.yaml" % tag)
        for rel, text in (files or {}).items():     # side files beside the config
            side = tmp_path / rel
            side.parent.mkdir(parents=True, exist_ok=True)
            side.write_text(text)
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


# ---------------------------------------------------------------------------
# Part 2: multi-task configs
# ---------------------------------------------------------------------------

def make_multi_config(url, tasks, defaults=None):
    """A `defaults` + `tasks` config in the Part 2 shape."""
    base = {
        "api_url": url,
        "model": "gpt-4",
        "rpm": 60,
        "generation": {"max_tokens": 256},
    }
    if defaults:
        for k, v in defaults.items():
            if v is None:
                base.pop(k, None)
            else:
                base[k] = v
    return {"defaults": base, "tasks": tasks}


class MultiCliResult:
    def __init__(self, proc, out_dir, data_dir):
        self.proc = proc
        self.code = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr
        self.out_dir = out_dir
        self.data_dir = data_dir

    def path(self, task):
        return self.out_dir / ("%s.jsonl" % task)

    def rows(self, task):
        text = self.path(task).read_text()
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    @property
    def outputs(self):
        """Names of the task output files actually written."""
        if not self.out_dir.is_dir():
            return []
        return sorted(p.name for p in self.out_dir.iterdir())

    @property
    def summary(self):
        lines = [l for l in self.stdout.splitlines() if l.strip()]
        assert lines, "no summary on stdout; stderr=%s" % self.stderr
        return json.loads(lines[-1])


@pytest.fixture
def run_multi(tmp_path):
    """Run the CLI against a multi-task config.

    `inputs` maps task name -> list of rows; files are written as
    `<data_dir>/<task>.jsonl`. `mode` picks the input flag style:
    "explicit" passes `--input <task>=<path>`, "dir" passes `--input-dir`,
    "none" passes neither.
    """
    counter = {"n": 0}

    def _run(config, inputs, *, args=(), mode="explicit", timeout=120,
             config_text=None, make_out_dir=True, out_name="out", files=None):
        counter["n"] += 1
        base = tmp_path / ("multi%d" % counter["n"])
        base.mkdir()
        cfg_path = base / "config.yaml"
        cfg_path.write_text(config_text if config_text is not None
                            else yaml.safe_dump(config))
        for rel, text in (files or {}).items():     # side files beside the config
            side = base / rel
            side.parent.mkdir(parents=True, exist_ok=True)
            side.write_text(text)
        data_dir = base / "data"
        data_dir.mkdir()
        flags = []
        for name, rows in (inputs or {}).items():
            path = data_dir / ("%s.jsonl" % name)
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
            if mode == "explicit":
                flags += ["--input", "%s=%s" % (name, path)]
        if mode == "dir":
            flags += ["--input-dir", str(data_dir)]
        out_dir = base / out_name
        if make_out_dir:
            out_dir.mkdir()
        cmd = [sys.executable, str(REJECTOR), "run",
               "--config", str(cfg_path), "--output", str(out_dir)]
        cmd += flags + [str(a) for a in args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return MultiCliResult(proc, out_dir, data_dir)

    return _run


def judge_split(api, gen_text, judge_text, delay=0.0):
    """Mock server that answers judge calls separately from generation calls.

    Judge requests are recognised by the word "evaluator" in their system
    message, matching the spec's judge_prompt example.
    """
    def responder(body, i):
        messages = body.get("messages") or [{}]
        system = messages[0].get("content", "")
        is_judge = "evaluator" in system
        text = judge_text if is_judge else gen_text
        if callable(text):
            text = text(body, i)
        return 200, completion(text, model=body.get("model", "gpt-4"))
    return api(responder, delay=delay)


# ---------------------------------------------------------------------------
# Part 5: background CLI runs (for observing a rate limiter mid-flight)
# ---------------------------------------------------------------------------

class BgRun:
    """A CLI process still running; inspect the mock server while it works."""

    def __init__(self, proc, out_path, log_path):
        self.proc = proc
        self.out_path = out_path
        self.log_path = log_path

    def wait(self, timeout=60):
        return self.proc.wait(timeout=timeout)

    def stop(self):
        """Terminate this one process by PID; never a pattern kill."""
        if self.proc.poll() is None:
            os.kill(self.proc.pid, signal.SIGKILL)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

    @property
    def log(self):
        return self.log_path.read_text() if self.log_path.exists() else ""

    @property
    def rows(self):
        if not self.out_path.exists():
            return []
        return [json.loads(l) for l in self.out_path.read_text().splitlines() if l.strip()]


@pytest.fixture
def run_cli_bg(tmp_path):
    """Start the CLI and return immediately.

    Output is redirected to a log file rather than an undrained pipe so a
    long-lived process can never block on a full buffer.
    """
    counter = {"n": 0}
    started = []

    def _run(config, rows, *, args=()):
        counter["n"] += 1
        tag = "bg%d" % counter["n"]
        cfg_path = tmp_path / ("%s.yaml" % tag)
        cfg_path.write_text(yaml.safe_dump(config))
        in_path = tmp_path / ("%s.jsonl" % tag)
        in_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        out_path = tmp_path / ("%s.out.jsonl" % tag)
        log_path = tmp_path / ("%s.log" % tag)
        cmd = [sys.executable, str(REJECTOR), "run",
               "--config", str(cfg_path), "--input", str(in_path),
               "--output", str(out_path)] + [str(a) for a in args]
        handle = log_path.open("w")
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT)
        run = BgRun(proc, out_path, log_path)
        started.append((run, handle))
        return run

    yield _run
    for run, handle in started:
        run.stop()
        handle.close()

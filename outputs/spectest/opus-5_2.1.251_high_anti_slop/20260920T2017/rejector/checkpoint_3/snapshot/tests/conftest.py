"""Shared helpers for the CLI tests: the mock server and how to invoke the CLI."""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOCK_SERVER = Path(__file__).resolve().parent / "mock_server.py"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_listening(port, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"mock server on port {port} never started")


@pytest.fixture
def server():
    """Start mock servers with given flags; they are stopped at teardown."""
    processes = []

    def start(*flags, workers=8, delay=0.05):
        port = free_port()
        command = [sys.executable, str(MOCK_SERVER), "--port", str(port),
                   "--workers", str(workers), "--delay", str(delay), *flags]
        processes.append(subprocess.Popen(command))
        wait_until_listening(port)
        return f"http://127.0.0.1:{port}"

    yield start
    for process in processes:
        process.terminate()
        process.wait()


def run_cli(*args):
    """Run `rejector.py run` with the given flags."""
    command = [sys.executable, str(ROOT / "rejector.py"), "run", *(str(arg) for arg in args)]
    return subprocess.run(command, capture_output=True, text=True, cwd=ROOT)


def read_results(output):
    return [json.loads(line) for line in Path(output).read_text().splitlines()]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path

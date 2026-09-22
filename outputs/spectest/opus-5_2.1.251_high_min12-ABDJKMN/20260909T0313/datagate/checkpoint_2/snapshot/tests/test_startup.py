"""Spec section: startup / command line.

    `datagate` starts with:
        python datagate.py start --port <port> --address <address>
    `--port` default `8001`. `--address` default `127.0.0.1`.
"""

import json
import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATAGATE = os.path.join(ROOT, "datagate.py")
LOG_DIR = os.path.join(ROOT, ".test-logs")


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Server:
    """Runs `python datagate.py start ...` as a child process.

    Output goes to a log file rather than an undrained pipe, and the process is
    stopped by its own PID (never a pattern-based kill)."""

    def __init__(self, args, name):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(LOG_DIR, "{}.log".format(name))
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, DATAGATE, "start"] + list(args),
            cwd=ROOT,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )

    def wait_until_listening(self, address, port, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(
                    "datagate exited early ({}); log:\n{}".format(
                        self.proc.returncode, self.log()
                    )
                )
            try:
                with socket.create_connection((address, port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def log(self):
        try:
            with open(self.log_path) as handle:
                return handle.read()
        except OSError:
            return ""

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()  # single known PID, not a pattern match
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._log.close()


@pytest.fixture
def server():
    started = []

    def _start(*args, name="datagate"):
        instance = _Server(args, name)
        started.append(instance)
        return instance

    yield _start
    for instance in started:
        instance.stop()


def _http_get(address, port, path, timeout=10.0):
    """Minimal HTTP GET so the startup tests do not depend on the app's client."""
    with socket.create_connection((address, port), timeout=timeout) as sock:
        request = "GET {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n".format(
            path, address, port
        )
        sock.sendall(request.encode("ascii"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split()[1])
    return status, body.decode("utf-8", "replace")


# Phrase: "`datagate` starts with: python datagate.py start --port <port> --address <address>"
def test_start_subcommand_with_explicit_port_and_address(server):
    port = _free_port()
    instance = server("--port", str(port), "--address", "127.0.0.1", name="explicit")
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()


# Phrase: "`--port` default `8001`."
def test_port_defaults_to_8001(server):
    instance = server("--address", "127.0.0.1", name="default-port")
    assert instance.wait_until_listening("127.0.0.1", 8001), instance.log()


# Phrase: "`--address` default `127.0.0.1`."
def test_address_defaults_to_127_0_0_1(server):
    port = _free_port()
    instance = server("--port", str(port), name="default-address")
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()


# Context: a server started via the documented command line actually serves the
# documented API (a spawned process, not just the in-process test client).
def test_started_server_serves_the_api(server):
    port = _free_port()
    instance = server("--port", str(port), name="serves-api")
    assert instance.wait_until_listening("127.0.0.1", port), instance.log()

    status, body = _http_get("127.0.0.1", port, "/convert")
    assert status == 400
    payload = json.loads(body)
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]

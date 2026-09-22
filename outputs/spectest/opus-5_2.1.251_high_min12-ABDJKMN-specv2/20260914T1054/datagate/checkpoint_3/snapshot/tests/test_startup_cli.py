"""Spec section: `datagate` startup / CLI."""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from conftest import unused_port

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")


def wait_for(url, proc, timeout=15.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError("server exited early with code %s" % proc.returncode)
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:  # server is up; it answered
            return e.code, json.loads(e.read().decode())
        except Exception as e:  # not listening yet
            last = e
            time.sleep(0.1)
    raise AssertionError("server never came up: %r" % last)


def spawn(args):
    """Start the server detached, with output to a file (never an undrained pipe)."""
    log = open("/tmp/datagate_test_server.log", "ab")
    return subprocess.Popen([PY, str(ROOT / "datagate.py")] + args,
                            stdout=log, stderr=log, cwd=str(ROOT))


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


# Phrase: "`datagate` starts with: python datagate.py start --port <port> --address <address>"
# Context: the documented invocation must start a server that serves the HTTP API.
def test_start_subcommand_with_explicit_port_and_address():
    port = unused_port()
    proc = spawn(["start", "--port", str(port), "--address", "127.0.0.1"])
    try:
        status, payload = wait_for("http://127.0.0.1:%d/datasets/nope" % port, proc)
        assert status == 404
        assert payload["ok"] is False
    finally:
        stop(proc)


# Phrase: "`--port` default `8001`."
# Context: omitting --port must bind 8001.
def test_port_defaults_to_8001():
    proc = spawn(["start", "--address", "127.0.0.1"])
    try:
        status, payload = wait_for("http://127.0.0.1:8001/datasets/nope", proc)
        assert status == 404
        assert payload["ok"] is False
    finally:
        stop(proc)


# Phrase: "`--address` default `127.0.0.1`."
# Context: omitting --address must bind the loopback address.
def test_address_defaults_to_loopback():
    port = unused_port()
    proc = spawn(["start", "--port", str(port)])
    try:
        status, _ = wait_for("http://127.0.0.1:%d/datasets/nope" % port, proc)
        assert status == 404
    finally:
        stop(proc)


# Phrase: "python datagate.py start" (both flags omitted)
# Context: all-default invocation is the documented minimum.
def test_all_defaults_invocation():
    proc = spawn(["start"])
    try:
        status, _ = wait_for("http://127.0.0.1:8001/datasets/nope", proc)
        assert status == 404
    finally:
        stop(proc)

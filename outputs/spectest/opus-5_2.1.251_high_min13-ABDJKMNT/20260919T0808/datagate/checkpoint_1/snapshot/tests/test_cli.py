"""Spec section: startup command and its option defaults."""

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from datagate import build_parser

REPO_ROOT = Path(__file__).resolve().parent.parent


# Phrase: "`datagate` starts with: python datagate.py start --port <port> --address <address>"
def test_start_command_accepts_port_and_address():
    args = build_parser().parse_args(["start", "--port", "9123", "--address", "0.0.0.0"])
    assert (args.command, args.port, args.address) == ("start", 9123, "0.0.0.0")


# Phrase: "`--port` default `8001`."
def test_port_defaults_to_8001():
    assert build_parser().parse_args(["start"]).port == 8001


# Phrase: "`--address` default `127.0.0.1`."
def test_address_defaults_to_localhost():
    assert build_parser().parse_args(["start"]).address == "127.0.0.1"


# Phrase: "--port <port>" is numeric, and a missing subcommand is rejected.
def test_port_is_an_integer_and_command_is_required():
    assert isinstance(build_parser().parse_args(["start", "--port", "8080"]).port, int)
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


# Phrase: the documented command line actually boots a server on the chosen port.
def test_start_serves_http_on_the_requested_address(tmp_path):
    log = (tmp_path / "server.log").open("w")
    process = subprocess.Popen(
        [sys.executable, "datagate.py", "start", "--port", "8123", "--address", "127.0.0.1"],
        cwd=REPO_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        body = _wait_for_http("http://127.0.0.1:8123/datasets/missing")
        assert b'"ok"' in body
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()


def _wait_for_http(url, attempts=50):
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            return error.read()
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"server never answered at {url}")

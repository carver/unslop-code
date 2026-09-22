"""Spec section: startup command line."""

import pathlib
import subprocess
import sys

import pytest

import datagate

ROOT = pathlib.Path(__file__).resolve().parents[1]


# Phrase: "`datagate` starts with: python datagate.py start --port <port> --address <address>"
def test_start_command_accepts_port_and_address():
    args = datagate.parse_args(["start", "--port", "9100", "--address", "0.0.0.0"])
    assert (args.command, args.port, args.address) == ("start", 9100, "0.0.0.0")


# Phrase: "`--port` default `8001`. `--address` default `127.0.0.1`."
def test_defaults_are_port_8001_and_localhost():
    args = datagate.parse_args(["start"])
    assert (args.port, args.address) == (8001, "127.0.0.1")


# Phrase (context: `--port <port>` is a port number): non-numeric ports are rejected.
def test_non_numeric_port_is_rejected():
    with pytest.raises(SystemExit):
        datagate.parse_args(["start", "--port", "http"])


# Phrase: "python datagate.py start" — the module is runnable as a script.
def test_script_entry_point_exposes_start_command():
    result = subprocess.run(
        [sys.executable, str(ROOT / "datagate.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "start" in result.stdout

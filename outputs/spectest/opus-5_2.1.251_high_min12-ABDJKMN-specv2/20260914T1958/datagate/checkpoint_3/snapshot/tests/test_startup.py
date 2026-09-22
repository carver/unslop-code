"""Spec section: startup command line."""
import requests

from conftest import free_port


# ---------------------------------------------------------------------------
# Phrase: "`datagate` starts with: `python datagate.py start --port <port>
#          --address <address>`"
# Context: startup contract.
# ---------------------------------------------------------------------------
def test_starts_with_start_subcommand_and_explicit_port_and_address(fresh_gate):
    port = free_port()
    gate = fresh_gate(port=port, address="127.0.0.1", subcommand="start")
    resp = gate.get("/datasets/nope")
    assert resp.status_code == 404
    assert gate.port == port


# ---------------------------------------------------------------------------
# Phrase: "`--port` default `8001`."
# Context: startup contract; port omitted from the command line.
# ---------------------------------------------------------------------------
def test_port_defaults_to_8001(fresh_gate):
    gate = fresh_gate(port=None, address="127.0.0.1", subcommand="start")
    assert gate.port == 8001
    resp = requests.get("http://127.0.0.1:8001/datasets/nope", timeout=10)
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "`--address` default `127.0.0.1`."
# Context: startup contract; address omitted from the command line.
# ---------------------------------------------------------------------------
def test_address_defaults_to_loopback(fresh_gate):
    port = free_port()
    gate = fresh_gate(port=port, address=None, subcommand="start")
    resp = requests.get(f"http://127.0.0.1:{port}/datasets/nope", timeout=10)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "--port <port> --address <address>" (both supplied together)
# Context: an explicitly chosen address is what actually gets bound.
# ---------------------------------------------------------------------------
def test_explicit_address_is_bound(fresh_gate):
    port = free_port()
    fresh_gate(port=port, address="127.0.0.1", subcommand="start")
    assert requests.get(f"http://127.0.0.1:{port}/datasets/nope", timeout=10).status_code == 404

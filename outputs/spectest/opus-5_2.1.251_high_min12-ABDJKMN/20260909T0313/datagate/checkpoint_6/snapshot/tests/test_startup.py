"""Spec section: startup / command line.

    `datagate` starts with:
        python datagate.py start --port <port> --address <address>
    `--port` default `8001`. `--address` default `127.0.0.1`.
"""

import json

from conftest import free_port as _free_port, http_get as _http_get


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

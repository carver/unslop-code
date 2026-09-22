"""Spec section: startup command line."""

import datagate


# Phrase: "`datagate` starts with: python datagate.py start --port <port> --address <address>"
def test_start_subcommand_accepts_port_and_address():
    args = datagate.build_parser().parse_args(
        ["start", "--port", "9100", "--address", "0.0.0.0"]
    )
    assert args.command == "start"
    assert args.port == 9100
    assert args.address == "0.0.0.0"


# Phrase: "`--port` default `8001`."
def test_port_defaults_to_8001():
    assert datagate.build_parser().parse_args(["start"]).port == 8001


# Phrase: "`--address` default `127.0.0.1`."
def test_address_defaults_to_127_0_0_1():
    assert datagate.build_parser().parse_args(["start"]).address == "127.0.0.1"


# Phrase: "starts with ... start" -- the command binds the app to the parsed host/port.
def test_main_serves_the_app_on_the_requested_socket(monkeypatch):
    calls = []
    monkeypatch.setattr(datagate, "serve", lambda address, port: calls.append((address, port)))

    datagate.main(["start", "--port", "9101"])

    assert calls == [("127.0.0.1", 9101)]

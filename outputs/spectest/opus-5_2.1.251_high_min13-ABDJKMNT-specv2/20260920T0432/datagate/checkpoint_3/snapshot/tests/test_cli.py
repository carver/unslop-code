"""Startup contract of the `datagate.py` command-line entry point."""

import datagate


# Spec: "`datagate` starts with: python datagate.py start --port <port> --address <address>"
# Context: the `start` subcommand accepts both options.
def test_start_command_accepts_port_and_address():
    args = datagate.build_parser().parse_args(
        ["start", "--port", "9100", "--address", "0.0.0.0"]
    )
    assert args.command == "start"
    assert args.port == 9100
    assert args.address == "0.0.0.0"


# Spec: "`--port` default `8001`."
# Context: omitting --port on the start command.
def test_port_defaults_to_8001():
    assert datagate.build_parser().parse_args(["start"]).port == 8001


# Spec: "`--address` default `127.0.0.1`."
# Context: omitting --address on the start command.
def test_address_defaults_to_127_0_0_1():
    assert datagate.build_parser().parse_args(["start"]).address == "127.0.0.1"


# Spec: "python datagate.py start ..."
# Context: `start` is the command that runs the server; main() wires the parsed
# options into the Flask app's listener.
def test_main_runs_app_with_parsed_host_and_port(monkeypatch):
    recorded = {}

    def fake_run(self, host=None, port=None, **kwargs):
        recorded.update(host=host, port=port)

    monkeypatch.setattr("flask.Flask.run", fake_run)
    datagate.main(["start", "--port", "9200", "--address", "0.0.0.0"])
    assert recorded == {"host": "0.0.0.0", "port": 9200}

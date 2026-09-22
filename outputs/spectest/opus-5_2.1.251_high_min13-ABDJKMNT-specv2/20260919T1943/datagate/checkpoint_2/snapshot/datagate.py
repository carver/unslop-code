"""Command line entry point: `python datagate.py start [--port] [--address]`."""

import argparse

from datagate_app.server import create_app

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="datagate.py", description="Serve remote CSV files as JSON datasets.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    start = subcommands.add_parser("start", help="Run the HTTP server.")
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on (default: %(default)s).")
    start.add_argument("--address", default=DEFAULT_ADDRESS, help="Address to bind (default: %(default)s).")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_app().run(host=args.address, port=args.port)


if __name__ == "__main__":
    main()

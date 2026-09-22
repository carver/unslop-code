"""Command line entry point: `python datagate.py start --port <port> --address <address>`."""

import argparse

from datagate_core.caching import ConfigurationError
from datagate_core.server import create_app

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    """Build the `datagate` command line parser."""
    parser = argparse.ArgumentParser(prog="datagate", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="run the datagate HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to listen on")
    start.add_argument("--address", default=DEFAULT_ADDRESS, help="address to bind to")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        app = create_app()
    except ConfigurationError as error:
        raise SystemExit(f"datagate: {error}")
    app.run(host=args.address, port=args.port)


if __name__ == "__main__":
    main()

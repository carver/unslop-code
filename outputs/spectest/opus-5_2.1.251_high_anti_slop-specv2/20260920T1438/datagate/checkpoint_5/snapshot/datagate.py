"""Command line entry point of the datagate service."""

import argparse

from gateway.app import create_app
from gateway.caching import ConfigurationError

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    """Define the ``datagate start`` command and its options."""
    parser = argparse.ArgumentParser(
        prog="datagate", description="Serve remote CSV files as JSON datasets."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="run the HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--address", default=DEFAULT_ADDRESS)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        app = create_app()
    except ConfigurationError as exc:
        raise SystemExit(f"datagate: {exc}") from exc
    app.run(host=arguments.address, port=arguments.port)


if __name__ == "__main__":
    main()

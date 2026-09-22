"""Command-line entry point: `python datagate.py start [--port] [--address]`."""

import argparse

from gateway.app import create_app
from gateway.config import ConfigError

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datagate", description="Serve remote CSV files as JSON datasets."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="run the HTTP server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="listen port")
    start.add_argument("--address", default=DEFAULT_ADDRESS, help="bind address")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        app = create_app()
    except ConfigError as exc:
        raise SystemExit(f"datagate: {exc}") from exc
    app.run(host=args.address, port=args.port, threaded=True)


if __name__ == "__main__":
    main()

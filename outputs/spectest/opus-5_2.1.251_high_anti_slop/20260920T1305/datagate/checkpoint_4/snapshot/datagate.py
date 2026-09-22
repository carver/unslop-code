"""Command line entry point: ``python datagate.py start [--port] [--address]``."""

import argparse

from datagate.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="datagate", description="Serve remote CSV files as JSON datasets."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="run the HTTP server")
    start.add_argument("--port", type=int, default=8001, help="port to listen on")
    start.add_argument(
        "--address", default="127.0.0.1", help="interface address to bind"
    )
    args = parser.parse_args()

    create_app().run(host=args.address, port=args.port)


if __name__ == "__main__":
    main()

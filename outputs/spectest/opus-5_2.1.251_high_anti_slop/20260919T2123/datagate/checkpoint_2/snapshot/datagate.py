"""Command line entry point for the datagate service."""

import argparse

from app import create_app

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(prog="datagate", description=__doc__)
    # `dest` is required alongside `required=True` for argparse to report a missing subcommand.
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Run the HTTP service")
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    start.add_argument("--address", default=DEFAULT_ADDRESS, help="Address to bind to")
    args = parser.parse_args()

    create_app().run(host=args.address, port=args.port, threaded=True)


if __name__ == "__main__":
    main()

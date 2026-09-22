"""Command line entry point: `python datagate.py start [--port] [--address]`."""

import argparse

from datagate_core.server import create_app

DEFAULT_PORT = 8001
DEFAULT_ADDRESS = "127.0.0.1"


def build_parser():
    """Build the `datagate` argument parser."""
    parser = argparse.ArgumentParser(prog="datagate", description="CSV ingestion gateway.")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Run the HTTP server.")
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on.")
    start.add_argument("--address", default=DEFAULT_ADDRESS, help="Address to bind to.")
    return parser


def serve(address, port):
    """Run the datagate application on `address:port` until interrupted."""
    create_app().run(host=address, port=port, threaded=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    serve(args.address, args.port)


if __name__ == "__main__":
    main()

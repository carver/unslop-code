"""Command line entry point for the datagate CSV gateway."""

import argparse

from app import create_app


def main():
    parser = argparse.ArgumentParser(prog="datagate", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="run the HTTP server")
    start.add_argument("--port", type=int, default=8001, help="port to listen on")
    start.add_argument("--address", default="127.0.0.1", help="address to bind to")

    args = parser.parse_args()
    create_app().run(host=args.address, port=args.port)


if __name__ == "__main__":
    main()

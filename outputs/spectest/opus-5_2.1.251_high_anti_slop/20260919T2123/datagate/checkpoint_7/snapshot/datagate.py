"""Command line entry point for the datagate service."""

import argparse

from app import create_app
from config import load_settings

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

    # An unusable configuration, an unreadable config file and an unusable storage directory are
    # all startup failures: the service reports them and exits rather than running misconfigured.
    try:
        app = create_app(load_settings())
    except (ValueError, OSError) as exc:
        raise SystemExit(f"{parser.prog}: {exc}") from exc

    app.run(host=args.address, port=args.port, threaded=True)


if __name__ == "__main__":
    main()

"""Command line entry point for mvault.

    python mvault.py init <name> <url>
    python mvault.py sync <name>
"""

import argparse
import sys

from mvaultlib.catalog import init_vault
from mvaultlib.errors import MvaultError
from mvaultlib.sync import sync_vault

USAGE_EXIT_CODE = 2
ERROR_EXIT_CODE = 1


def build_parser():
    """Build the CLI parser, whose help lists the available subcommands."""
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata and record "
        "tracked-field history by sync timestamp.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source metadata URL")
    init.set_defaults(run=lambda args: init_vault(args.name, args.url))

    sync = subcommands.add_parser("sync", help="update a vault from its source URL")
    sync.add_argument("name", help="existing vault directory")
    sync.set_defaults(run=lambda args: sync_vault(args.name))

    return parser


def main(argv):
    """Run one CLI invocation and return its exit code."""
    parser = build_parser()
    if not argv:
        parser.print_usage(sys.stderr)
        print("mvault: a subcommand is required (init, sync)", file=sys.stderr)
        return USAGE_EXIT_CODE

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except MvaultError as error:
        print(f"mvault: error: {error}", file=sys.stderr)
        return ERROR_EXIT_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Command-line surface for mvault."""

import argparse
import sys

from .errors import MvaultError
from .sync import sync_vault
from .vault import init_vault

DESCRIPTION = "Create local vaults for media-platform metadata and track field history."


def build_parser():
    parser = argparse.ArgumentParser(prog="mvault.py", description=DESCRIPTION)
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source URL the vault syncs from")

    sync = subcommands.add_parser("sync", help="sync a vault against its source URL")
    sync.add_argument("name", help="vault directory to sync")

    return parser


def main(argv=None):
    """Run one CLI invocation and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2

    try:
        if args.command == "init":
            init_vault(args.name, args.url)
        else:
            sync_vault(args.name)
    except MvaultError as error:
        print(error, file=sys.stderr)
        return 1
    return 0

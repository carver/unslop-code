"""Argument parsing and error reporting for the `mvault` command line."""

import argparse
import sys

from .commands import init_vault, sync_vault
from .errors import MvaultError

USAGE_EXIT_CODE = 2
ERROR_EXIT_CODE = 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and track field history.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source URL the vault syncs from")

    sync = subcommands.add_parser("sync", help="fetch the source and update a vault's catalog")
    sync.add_argument("name", help="vault directory to sync")

    return parser


def main(argv=None):
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return USAGE_EXIT_CODE

    try:
        if args.command == "init":
            init_vault(args.name, args.url)
        else:
            sync_vault(args.name)
    except MvaultError as error:
        print(f"mvault: error: {error}", file=sys.stderr)
        return ERROR_EXIT_CODE
    return 0

"""Argument parsing and error reporting for the `mvault` command line."""

import argparse
import sys

from .commands import init_vault, migrate_vault, sync_vault
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
    init.set_defaults(run=lambda args: init_vault(args.name, args.url))

    sync = subcommands.add_parser("sync", help="fetch the source and update a vault's catalog")
    sync.add_argument("name", help="vault directory to sync")
    sync.set_defaults(run=lambda args: sync_vault(args.name))

    migrate = subcommands.add_parser("migrate", help="convert a legacy catalog to the current format")
    migrate.add_argument("name", help="vault directory to migrate")
    migrate.set_defaults(run=lambda args: migrate_vault(args.name))

    return parser


def main(argv=None):
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return USAGE_EXIT_CODE

    try:
        args.run(args)
    except MvaultError as error:
        print(f"mvault: error: {error}", file=sys.stderr)
        return ERROR_EXIT_CODE
    return 0

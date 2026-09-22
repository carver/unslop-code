#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Usage:
    python mvault.py init <name> <url>
    python mvault.py sync <name>
    python mvault.py migrate <name>
"""

import argparse
import sys
from datetime import datetime

from mvaultlib import catalog, sync
from mvaultlib.errors import MvaultError
from mvaultlib.schema import VERSION


def init_command(args):
    """Create a new vault directory holding an empty catalog."""
    catalog.create(args.name, args.url)
    print(f"initialized vault '{args.name}' from {args.url}")


def sync_command(args):
    """Fetch the vault's source and record the observation in its catalog."""
    stamp = sync.sync(args.name, datetime.now())
    print(f"synced vault '{args.name}' at {stamp}")


def migrate_command(args):
    """Rewrite a legacy catalog in the native format, in place."""
    if catalog.migrate(args.name):
        print(f"migrated vault '{args.name}' to version {VERSION}")
    else:
        print(f"vault '{args.name}' already uses version {VERSION}")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and track field history.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>", required=True)

    init_parser = subcommands.add_parser("init", help="create a new vault at <name>/ for <url>")
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source URL for media metadata")
    init_parser.set_defaults(handler=init_command)

    sync_parser = subcommands.add_parser("sync", help="sync the vault at <name>/ with its source")
    sync_parser.add_argument("name", help="existing vault directory")
    sync_parser.set_defaults(handler=sync_command)

    migrate_parser = subcommands.add_parser("migrate", help="convert the catalog at <name>/ to the native version")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(handler=migrate_command)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except MvaultError as error:
        print(f"mvault: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

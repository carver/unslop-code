#!/usr/bin/env python3
"""Command line entry point for mvault.

mvault creates local vaults for media-platform metadata and records the history
of tracked fields by sync timestamp.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from vault import catalog, source, syncing, versions
from vault.errors import MVaultError


def init_vault(name, url):
    """Create the vault directory ``name`` holding an empty catalog for ``url``."""
    directory = Path(name)
    if directory.exists():
        raise MVaultError(f"vault '{name}' already exists")
    directory.mkdir(parents=True)
    catalog.save(name, catalog.new_catalog(url))


def sync_vault(name):
    """Fetch the vault source and fold the result into its catalog.

    A legacy catalog is migrated in memory first, so the sync is written back in
    the native version.
    """
    stored = versions.load(name)
    fetched = source.fetch(stored["source"])
    moment = syncing.sync_timestamp(stored, datetime.now().replace(microsecond=0))
    syncing.apply_source(stored, fetched, moment)
    catalog.save(name, stored)


def migrate_vault(name):
    """Convert a legacy catalog on disk to the native version; native vaults are untouched."""
    migrated, changed = versions.to_current(catalog.read_document(name), name)
    if changed:
        catalog.save(name, migrated)


def build_parser():
    """Build the argument parser for the ``init``, ``sync`` and ``migrate`` subcommands."""
    parser = argparse.ArgumentParser(
        prog="mvault.py", description="Create and update local media metadata vaults."
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>", required=True)

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source URL to fetch metadata from")
    init.set_defaults(run=lambda args: init_vault(args.name, args.url))

    sync = subcommands.add_parser("sync", help="update a vault from its source")
    sync.add_argument("name", help="existing vault directory")
    sync.set_defaults(run=lambda args: sync_vault(args.name))

    migrate = subcommands.add_parser("migrate", help="convert a legacy catalog to the current version")
    migrate.add_argument("name", help="existing vault directory")
    migrate.set_defaults(run=lambda args: migrate_vault(args.name))

    return parser


def main(argv=None):
    """Run a subcommand and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except MVaultError as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

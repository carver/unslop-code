#!/usr/bin/env python3
"""Command line entry point for mvault.

mvault creates local vaults for media-platform metadata and records the history
of tracked fields by sync timestamp.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from vault import catalog, digest, downloads, source, syncing, versions
from vault.catalog import CATEGORIES
from vault.errors import MVaultError
from vault.history import format_timestamp


def init_vault(name, url):
    """Create the vault directory ``name`` holding an empty catalog for ``url``."""
    directory = Path(name)
    if directory.exists():
        raise MVaultError(f"vault '{name}' already exists")
    directory.mkdir(parents=True)
    catalog.save(name, catalog.new_catalog(url))


def sync_vault(args):
    """Update a vault: first the metadata phase, then the download phase.

    A legacy catalog is migrated in memory first, so the sync is written back in
    the native version and the downloads use the migrated source URL. The
    metadata phase is saved before the downloads start, so failing downloads
    never cost the metadata the run already gathered.
    """
    stored = versions.load(args.name)
    if not args.skip_metadata:
        fetched = source.fetch(stored["source"])
        moment = syncing.sync_timestamp(stored, datetime.now().replace(microsecond=0))
        summary = syncing.apply_source(stored, fetched, moment)
        catalog.save(args.name, stored)
        print(f"{summary.added} added, {summary.removed} removed, {summary.updated} updated")
    if not args.skip_download:
        limits = {category: getattr(args, category) for category in CATEGORIES}
        downloads.run(args.name, stored, limits, args.format)


def digest_vault(name):
    """Print the notable changes of a vault of any supported version, without writing to it."""
    print(digest.report(name, format_timestamp(datetime.now().replace(microsecond=0))))


def migrate_vault(name):
    """Convert a legacy catalog on disk to the native version; native vaults are untouched."""
    migrated, changed = versions.to_current(catalog.read_document(name), name)
    if changed:
        catalog.save(name, migrated)


def category_limit(text):
    """Parse a per-category download limit given on the command line."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"'{text}' is not a non-negative integer")
    return int(text)


def build_parser():
    """Build the argument parser for the mvault subcommands."""
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
    for category in CATEGORIES:
        sync.add_argument(
            f"--{category}",
            type=category_limit,
            metavar="<n>",
            help=f"download at most <n> {category} whose media is missing",
        )
    sync.add_argument(
        "--skip-metadata", action="store_true", help="download only, leaving the catalog as it is"
    )
    sync.add_argument(
        "--skip-download", action="store_true", help="update the catalog without downloading"
    )
    sync.add_argument(
        "--format", metavar="<str>", help="media format to request, also used as the extension"
    )
    sync.set_defaults(run=sync_vault)

    summary = subcommands.add_parser("digest", help="summarize the notable changes in a vault")
    summary.add_argument("name", help="existing vault directory")
    summary.set_defaults(run=lambda args: digest_vault(args.name))

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

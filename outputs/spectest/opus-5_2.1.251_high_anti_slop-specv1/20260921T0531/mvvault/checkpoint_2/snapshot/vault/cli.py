"""Command line interface for mvault."""

import argparse
import sys
from datetime import datetime

from . import catalog, source, sync
from .errors import VaultError
from .timestamps import SyncClock


def build_parser():
    """Build the ``mvault.py`` argument parser and its subcommands."""
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults of media-platform metadata and track field history.",
    )
    subcommands = parser.add_subparsers(dest="command", title="subcommands")

    initializer = subcommands.add_parser("init", help="create a new vault for a source URL")
    initializer.add_argument("name", help="vault directory to create")
    initializer.add_argument("url", help="source metadata URL")
    initializer.set_defaults(handler=_init)

    syncer = subcommands.add_parser("sync", help="update a vault from its source")
    syncer.add_argument("name", help="existing vault directory")
    syncer.set_defaults(handler=_sync)

    migrator = subcommands.add_parser("migrate", help="rewrite a legacy catalog in the current format")
    migrator.add_argument("name", help="existing vault directory")
    migrator.set_defaults(handler=_migrate)

    return parser


def _init(args):
    """Handle ``mvault.py init <name> <url>``."""
    catalog.create(args.name, args.url)


def _sync(args):
    """Handle ``mvault.py sync <name>``.

    The catalog is loaded and the snapshot validated before anything is
    written, so a failing source leaves the vault untouched. A legacy catalog
    is upgraded on the way in and stored back in the current format.
    """
    stored = catalog.load(args.name).catalog
    snapshot = source.fetch(stored["source"])
    sync.merge(stored, snapshot, SyncClock(datetime.now()))
    catalog.save(args.name, stored)


def _migrate(args):
    """Handle ``mvault.py migrate <name>``.

    Loading does the upgrade, so only a vault that really held a legacy
    catalog is written back; an up-to-date one is left alone entirely.
    """
    loaded = catalog.load(args.name)
    if loaded.upgraded:
        catalog.save(args.name, loaded.catalog)


def _fail(message):
    print(f"mvault: {message}", file=sys.stderr)
    return 1


def main(argv=None):
    """Run one command line invocation and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2
    try:
        args.handler(args)
    except VaultError as error:
        return _fail(str(error))
    except source.SourceError as error:
        return _fail(f"Source metadata fetch failure: {error}")
    return 0

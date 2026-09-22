"""Command line interface for mvault."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import catalog, digest, download, links, report, source, sync, viewer
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
    for category in source.CATEGORIES:
        syncer.add_argument(
            f"--{category}",
            type=_limit,
            metavar="N",
            help=f"download at most N {category} (default: all that are missing)",
        )
    syncer.add_argument(
        "--skip-metadata", action="store_true", help="download only, leaving the catalog as it is"
    )
    syncer.add_argument(
        "--skip-download", action="store_true", help="update the catalog without downloading"
    )
    syncer.add_argument(
        "--format", metavar="EXT", help="media format to request and store media files under"
    )
    syncer.set_defaults(handler=_sync)

    migrator = subcommands.add_parser(
        "migrate", help="rewrite a legacy catalog in the current format"
    )
    migrator.add_argument("name", help="existing vault directory")
    migrator.set_defaults(handler=_migrate)

    digester = subcommands.add_parser("digest", help="report a vault's notable changes")
    digester.add_argument("name", help="existing vault directory")
    digester.set_defaults(handler=_digest)

    server = subcommands.add_parser("serve", help="browse the vaults here in a web viewer")
    server.add_argument("name", nargs="?", help="vault to open the browser on")
    server.add_argument(
        "--host",
        default=links.DEFAULT_HOST,
        metavar="HOST",
        help=f"address to bind and to open the browser on (default: {links.DEFAULT_HOST})",
    )
    server.add_argument(
        "--port",
        type=_port,
        default=links.DEFAULT_PORT,
        metavar="PORT",
        help=f"port to listen on (default: {links.DEFAULT_PORT})",
    )
    server.set_defaults(handler=_serve)

    return parser


def _limit(text):
    """Read a per-category download limit, which counts and so is never negative."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"{text} is not a non-negative integer")
    return int(text)


def _port(text):
    """Read the port to listen on, which has to be one a socket can bind."""
    if not text.isdigit() or int(text) > 65535:
        raise argparse.ArgumentTypeError(f"{text} is not a TCP port number")
    return int(text)


def _init(args):
    """Handle ``mvault.py init <name> <url>``."""
    catalog.create(args.name, args.url)


def _sync(args):
    """Handle ``mvault.py sync <name> [options]``.

    The metadata phase loads the catalog and validates the snapshot before
    anything is written, so a failing source leaves the vault untouched, and a
    legacy catalog is upgraded on the way in and stored back in the current
    format. It is also saved before the download phase begins, so downloads
    that fail cannot cost the vault the metadata it just gained.
    """
    stored = catalog.load(args.name).catalog
    if not args.skip_metadata:
        changes = sync.merge(stored, source.fetch(stored["source"]), SyncClock(datetime.now()))
        catalog.save(args.name, stored)
        print(report.sync_summary(args.name, changes))
    if not args.skip_download:
        limits = {category: getattr(args, category) for category in source.CATEGORIES}
        download.run(args.name, stored, limits, args.format)


def _migrate(args):
    """Handle ``mvault.py migrate <name>``.

    Loading does the upgrade, so only a vault that really held a legacy
    catalog is written back; an up-to-date one is left alone entirely.
    """
    loaded = catalog.load(args.name)
    if loaded.upgraded:
        catalog.save(args.name, loaded.catalog)


def _digest(args):
    """Handle ``mvault.py digest <name>``.

    The catalog is read in whatever version it stores and never written, so a
    legacy vault is digested without being migrated first.
    """
    print(report.render_digest(digest.load(args.name), args.name, datetime.now()))


def _serve(args):
    """Handle ``mvault.py serve [<name>] [--host=<host>] [--port=<port>]``.

    The viewer serves the vaults of the working directory it was started in,
    and runs until it is interrupted.
    """
    viewer.serve(Path.cwd(), args.name, args.host, args.port)


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

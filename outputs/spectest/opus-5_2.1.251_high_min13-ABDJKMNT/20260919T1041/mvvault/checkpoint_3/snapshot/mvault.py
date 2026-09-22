#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Usage:
    python mvault.py init <name> <url>
    python mvault.py sync <name> [options]
    python mvault.py migrate <name>
    python mvault.py digest <name>
"""

import argparse
import sys
from datetime import datetime

from mvaultlib import catalog, digest, digest_report, download, sync, timestamps
from mvaultlib.errors import MvaultError
from mvaultlib.schema import CATEGORIES, VERSION


def init_command(args):
    """Create a new vault directory holding an empty catalog."""
    catalog.create(args.name, args.url)
    print(f"initialized vault '{args.name}' from {args.url}")


def sync_command(args):
    """Run the metadata phase, then the download phase, as the flags allow."""
    if args.skip_metadata:
        vault_catalog, _ = catalog.load(args.name)
    else:
        vault_catalog, stamp, counts = sync.metadata_phase(args.name, datetime.now())
        print(f"synced vault '{args.name}' at {stamp}")
        print("changes: " + ", ".join(f"{counts[kind]} {kind}" for kind in sync.CHANGE_KINDS))

    if not args.skip_download:
        limits = {category: getattr(args, category) for category in CATEGORIES}
        download.run(args.name, vault_catalog, limits, args.media_format)


def migrate_command(args):
    """Rewrite a legacy catalog in the native format, in place."""
    if catalog.migrate(args.name):
        print(f"migrated vault '{args.name}' to version {VERSION}")
    else:
        print(f"vault '{args.name}' already uses version {VERSION}")


def digest_command(args):
    """Summarize a vault's notable changes, reading it at its own version."""
    view = digest.load_view(args.name)
    print(digest_report.render(args.name, view, timestamps.current_stamp()))


def download_limit(text):
    """A `--episodes`/`--streams`/`--clips` value: a non-negative integer."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got '{text}'")
    return int(text)


def media_format(text):
    """A `--format` value: the bare format name, so a leading dot is ignored."""
    return text.lstrip(".")


def add_sync_options(parser):
    """The phase flags and per-category download limits of `sync`."""
    for category in CATEGORIES:
        parser.add_argument(
            f"--{category}",
            type=download_limit,
            metavar="<n>",
            help=f"download at most <n> {category[:-1]} media files",
        )
    parser.add_argument("--skip-metadata", action="store_true", help="skip the source fetch and metadata update")
    parser.add_argument("--skip-download", action="store_true", help="skip the download phase")
    parser.add_argument(
        "--format",
        dest="media_format",
        type=media_format,
        metavar="<str>",
        help="request media in this format and store it with that extension",
    )


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
    add_sync_options(sync_parser)
    sync_parser.set_defaults(handler=sync_command)

    migrate_parser = subcommands.add_parser("migrate", help="convert the catalog at <name>/ to the native version")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(handler=migrate_command)

    digest_parser = subcommands.add_parser("digest", help="summarize notable changes in the vault at <name>/")
    digest_parser.add_argument("name", help="existing vault directory")
    digest_parser.set_defaults(handler=digest_command)

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

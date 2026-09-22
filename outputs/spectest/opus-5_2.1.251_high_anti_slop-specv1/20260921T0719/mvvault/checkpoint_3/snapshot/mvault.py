"""Command line entry point for mvault.

mvault keeps a local vault of media-platform metadata, records how the tracked
fields of each entry change from one sync to the next, and downloads the media
behind those entries.
"""

import argparse
import sys
from typing import Optional, Sequence

import catalogs
from digest import digest_vault
from errors import MvaultError
from vault import SyncOptions, init_vault, migrate_vault, sync_vault


def build_parser() -> argparse.ArgumentParser:
    """Assemble the ``init``, ``sync``, ``migrate`` and ``digest`` command line."""
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="directory of the vault to create")
    init.add_argument("url", help="source URL the vault tracks")
    init.set_defaults(run=lambda args: init_vault(args.name, args.url))

    sync = subcommands.add_parser(
        "sync", help="record the current source state in a vault and download its media"
    )
    sync.add_argument("name", help="directory of an existing vault")
    for category in catalogs.CATEGORIES:
        sync.add_argument(
            f"--{category}",
            type=category_limit,
            metavar="<n>",
            help=f"download at most <n> {category} media files",
        )
    sync.add_argument(
        "--skip-metadata",
        action="store_true",
        help="download files only, leaving the catalog as it is",
    )
    sync.add_argument(
        "--skip-download",
        action="store_true",
        help="update the catalog only, downloading no files",
    )
    sync.add_argument(
        "--format",
        metavar="<str>",
        help="media format to request, and the extension to store it under",
    )
    sync.set_defaults(run=lambda args: sync_vault(args.name, sync_options(args)))

    migrate = subcommands.add_parser(
        "migrate", help="rewrite a legacy catalog in the current version"
    )
    migrate.add_argument("name", help="directory of an existing vault")
    migrate.set_defaults(run=lambda args: migrate_vault(args.name))

    digest = subcommands.add_parser(
        "digest", help="summarize the notable changes recorded in a vault"
    )
    digest.add_argument("name", help="directory of an existing vault")
    digest.set_defaults(run=lambda args: digest_vault(args.name))

    return parser


def category_limit(text: str) -> int:
    """Read a per-category download cap, refusing anything but a count."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, not '{text}'")
    return int(text)


def sync_options(args: argparse.Namespace) -> SyncOptions:
    """Collect the download options a parsed ``sync`` command line carries."""
    return SyncOptions(
        limits={category: getattr(args, category) for category in catalogs.CATEGORIES},
        media_format=args.format,
        skip_metadata=args.skip_metadata,
        skip_download=args.skip_download,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run a subcommand and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        print(args.run(args))
    except MvaultError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

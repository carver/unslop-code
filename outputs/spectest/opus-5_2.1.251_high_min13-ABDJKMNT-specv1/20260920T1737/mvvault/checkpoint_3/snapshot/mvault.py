"""Command line entry point for mvault.

    python mvault.py init <name> <url>
    python mvault.py sync <name> [options]
    python mvault.py migrate <name>
    python mvault.py digest <name>
"""

import argparse
import sys

from mvaultlib.catalog import init_vault
from mvaultlib.digest import digest_vault
from mvaultlib.entries import CATEGORIES
from mvaultlib.errors import MvaultError
from mvaultlib.migrate import migrate_vault
from mvaultlib.sync import SyncOptions, sync_vault

USAGE_EXIT_CODE = 2
ERROR_EXIT_CODE = 1


def download_limit(text):
    """Read a per-category download limit, which must be a non-negative integer."""
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"'{text}' is negative")
    return value


def build_parser():
    """Build the CLI parser, whose help lists the available subcommands."""
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata and record "
        "tracked-field history by sync timestamp.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source metadata URL")
    init.set_defaults(run=lambda args: init_vault(args.name, args.url))

    sync = subcommands.add_parser("sync", help="update a vault from its source URL")
    sync.add_argument("name", help="existing vault directory")
    for category in CATEGORIES:
        sync.add_argument(
            f"--{category}",
            type=download_limit,
            metavar="<n>",
            help=f"download at most <n> {category[:-1]} media files",
        )
    sync.add_argument(
        "--format",
        dest="format_override",
        metavar="<str>",
        help="request this media format and use it as the file extension",
    )
    sync.add_argument("--skip-metadata", action="store_true", help="download only")
    sync.add_argument("--skip-download", action="store_true", help="fetch metadata only")
    sync.set_defaults(run=lambda args: sync_vault(args.name, SyncOptions.from_args(args)))

    migrate = subcommands.add_parser("migrate", help="convert a legacy vault catalog to version 3")
    migrate.add_argument("name", help="existing vault directory")
    migrate.set_defaults(run=lambda args: migrate_vault(args.name))

    digest = subcommands.add_parser("digest", help="summarize notable changes in a vault")
    digest.add_argument("name", help="existing vault directory")
    digest.set_defaults(run=lambda args: digest_vault(args.name))

    return parser


def main(argv):
    """Run one CLI invocation and return its exit code."""
    parser = build_parser()
    if not argv:
        parser.print_usage(sys.stderr)
        print("mvault: a subcommand is required (init, sync, migrate, digest)", file=sys.stderr)
        return USAGE_EXIT_CODE

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except MvaultError as error:
        print(f"mvault: error: {error}", file=sys.stderr)
        return ERROR_EXIT_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

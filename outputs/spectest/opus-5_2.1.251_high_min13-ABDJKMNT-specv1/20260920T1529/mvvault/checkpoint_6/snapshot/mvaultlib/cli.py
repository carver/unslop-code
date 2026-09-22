"""Command-line surface for mvault."""

import argparse
import sys

from .digest import digest_vault
from .errors import MvaultError
from .source import CATEGORIES
from .server import serve_viewer
from .sync import SyncOptions, sync_vault
from .vault import init_vault, migrate_vault
from .viewer import DEFAULT_HOST, DEFAULT_PORT

DESCRIPTION = "Create local vaults for media-platform metadata and track field history."


def download_limit(text):
    """A per-category download limit: a non-negative integer."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {text!r}")
    return int(text)


def build_parser():
    parser = argparse.ArgumentParser(prog="mvault.py", description=DESCRIPTION)
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source URL the vault syncs from")

    add_sync_parser(subcommands)

    migrate = subcommands.add_parser("migrate", help="convert a legacy catalog to version 3")
    migrate.add_argument("name", help="vault directory to migrate")

    digest = subcommands.add_parser("digest", help="summarise a vault's notable changes")
    digest.add_argument("name", help="vault directory to summarise")

    add_serve_parser(subcommands)

    return parser


def add_serve_parser(subcommands):
    """Declare `serve`, its optional vault name and its bind overrides."""
    serve = subcommands.add_parser("serve", help="browse vaults in a local viewer")
    serve.add_argument("name", nargs="?", help="vault to open in the browser")
    serve.add_argument("--host", default=DEFAULT_HOST, metavar="<host>", help="bind host")
    serve.add_argument(
        "--port", type=int, default=DEFAULT_PORT, metavar="<port>", help="bind port"
    )


def add_sync_parser(subcommands):
    """Declare `sync`, its per-category limits and its phase switches."""
    sync = subcommands.add_parser("sync", help="sync a vault against its source URL")
    sync.add_argument("name", help="vault directory to sync")
    for category in CATEGORIES:
        sync.add_argument(
            f"--{category}",
            type=download_limit,
            metavar="<n>",
            help=f"maximum number of {category} media downloads",
        )
    sync.add_argument("--format", metavar="<str>", help="media download format and extension")
    sync.add_argument("--skip-metadata", action="store_true", help="run the download phase only")
    sync.add_argument("--skip-download", action="store_true", help="run the metadata phase only")


def sync_options(args):
    """The `SyncOptions` the parsed `sync` arguments describe."""
    return SyncOptions(
        limits={category: getattr(args, category) for category in CATEGORIES},
        media_format=args.format,
        skip_metadata=args.skip_metadata,
        skip_download=args.skip_download,
    )


COMMANDS = {
    "init": lambda args: init_vault(args.name, args.url),
    "sync": lambda args: sync_vault(args.name, sync_options(args)),
    "migrate": lambda args: migrate_vault(args.name),
    "digest": lambda args: digest_vault(args.name),
    "serve": lambda args: serve_viewer(args.name, args.host, args.port),
}


def run(args):
    """Carry out one parsed subcommand."""
    COMMANDS[args.command](args)


def main(argv=None):
    """Run one CLI invocation and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2

    try:
        run(args)
    except MvaultError as error:
        print(error, file=sys.stderr)
        return 1
    return 0

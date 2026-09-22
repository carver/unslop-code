"""Argument parsing and error reporting for the `mvault` command line."""

import argparse
import sys

from .catalog import CATEGORIES
from .commands import SyncOptions, digest_vault, init_vault, migrate_vault, sync_vault
from .errors import MvaultError
from .links import DEFAULT_HOST, DEFAULT_PORT
from .server import run_viewer

USAGE_EXIT_CODE = 2
ERROR_EXIT_CODE = 1


def download_limit(text):
    """A category limit: a plain non-negative integer, nothing else."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {text!r}")
    return int(text)


def port_number(text):
    """A bind port: an integer in the range a server may actually listen on."""
    if not text.isdigit() or not 0 < int(text) <= 65535:
        raise argparse.ArgumentTypeError(f"expected a port number, got {text!r}")
    return int(text)


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
    _add_sync_options(sync)
    sync.set_defaults(run=lambda args: sync_vault(args.name, _sync_options(args)))

    migrate = subcommands.add_parser("migrate", help="convert a legacy catalog to the current format")
    migrate.add_argument("name", help="vault directory to migrate")
    migrate.set_defaults(run=lambda args: migrate_vault(args.name))

    digest = subcommands.add_parser("digest", help="summarize a vault's notable changes")
    digest.add_argument("name", help="vault directory to summarize")
    digest.set_defaults(run=lambda args: digest_vault(args.name))

    serve = subcommands.add_parser("serve", help="browse the vaults here in a local viewer")
    _add_serve_options(serve)
    serve.set_defaults(run=lambda args: run_viewer(args.name, args.host, args.port))

    return parser


def _add_serve_options(serve):
    """The optional vault to open, and the address the viewer binds."""
    serve.add_argument("name", nargs="?", help="vault to open the browser on")
    serve.add_argument(
        "--host", default=DEFAULT_HOST, metavar="<host>", help="host the viewer binds"
    )
    serve.add_argument(
        "--port",
        type=port_number,
        default=DEFAULT_PORT,
        metavar="<port>",
        help="port the viewer binds",
    )


def _add_sync_options(sync):
    """The per-category download limits, the format override and the phase switches."""
    for category in CATEGORIES:
        sync.add_argument(
            f"--{category}",
            type=download_limit,
            metavar="<n>",
            help=f"maximum number of {category} media downloads",
        )
    sync.add_argument(
        "--format",
        dest="media_format",
        metavar="<str>",
        help="override the media download format and output extension",
    )
    sync.add_argument(
        "--skip-metadata",
        action="store_true",
        help="skip the source fetch and metadata update; download only",
    )
    sync.add_argument(
        "--skip-download",
        action="store_true",
        help="skip the download phase; fetch and persist metadata only",
    )


def _sync_options(args):
    return SyncOptions(
        limits={category: getattr(args, category) for category in CATEGORIES},
        media_format=args.media_format,
        skip_metadata=args.skip_metadata,
        skip_download=args.skip_download,
    )


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

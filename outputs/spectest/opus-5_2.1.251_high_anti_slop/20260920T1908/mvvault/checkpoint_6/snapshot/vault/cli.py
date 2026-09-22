"""Command line interface for mvault."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .catalog import load_catalog, new_catalog, save_catalog
from .changes import ChangeSet
from .digest import collect_changes
from .download import download_assets
from .errors import ServerError, SourceError, VaultError
from .report import render_digest, render_sync_summary
from .schema import CATEGORIES
from .source import fetch_source
from .sync import merge_catalog
from .viewer.links import DEFAULT_HOST, DEFAULT_PORT
from .viewer.server import serve
from .views import read_view


def build_parser() -> argparse.ArgumentParser:
    """Define the ``init``, ``sync``, ``migrate``, ``digest`` and ``serve`` subcommands."""
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and record tracked-field history.",
    )
    subcommands = parser.add_subparsers(dest="subcommand", metavar="<subcommand>", required=True)

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source URL to record in the catalog")
    init.set_defaults(handler=run_init)

    sync = subcommands.add_parser(
        "sync", help="record the current source metadata in a vault and download its media"
    )
    sync.add_argument("name", help="vault directory to update")
    _add_sync_options(sync)
    sync.set_defaults(handler=run_sync)

    migrate = subcommands.add_parser(
        "migrate", help="rewrite an older catalog in the current format"
    )
    migrate.add_argument("name", help="vault directory to migrate")
    migrate.set_defaults(handler=run_migrate)

    digest = subcommands.add_parser("digest", help="summarize what changed in a vault")
    digest.add_argument("name", help="vault directory to summarize")
    digest.set_defaults(handler=run_digest)

    serve_command = subcommands.add_parser(
        "serve", help="browse the vaults of this directory in a local viewer"
    )
    serve_command.add_argument(
        "name", nargs="?", help="vault directory to open the browser at (default: the landing page)"
    )
    serve_command.add_argument(
        "--host", default=DEFAULT_HOST, metavar="<host>", help="bind address (default: %(default)s)"
    )
    serve_command.add_argument(
        "--port", type=int, default=DEFAULT_PORT, metavar="<port>", help="bind port (default: %(default)s)"
    )
    serve_command.set_defaults(handler=run_serve)
    return parser


def _add_sync_options(sync: argparse.ArgumentParser) -> None:
    """Add the options that pick which halves of a sync run, and how much."""
    for category in CATEGORIES:
        sync.add_argument(
            f"--{category}",
            type=_limit,
            metavar="<n>",
            help=f"download the media of at most <n> {category} (default: all of them)",
        )
    sync.add_argument(
        "--skip-metadata",
        action="store_true",
        help="do not fetch the source; download against the stored catalog",
    )
    sync.add_argument(
        "--skip-download", action="store_true", help="fetch and store metadata only"
    )
    sync.add_argument(
        "--format",
        metavar="<str>",
        help="request media in this format and give the stored files its extension",
    )


def _limit(text: str) -> int:
    """Read a per-category download limit, which counts entries and so is never negative."""
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"'{text}' is not a non-negative integer")
    return int(text)


def run_init(args: argparse.Namespace) -> None:
    """Create ``<name>/`` holding an empty catalog for ``<url>``."""
    vault_dir = Path(args.name)
    if vault_dir.exists():
        raise VaultError(f"vault '{args.name}' already exists")
    vault_dir.mkdir(parents=True)
    save_catalog(vault_dir, new_catalog(args.url))


def run_sync(args: argparse.Namespace) -> None:
    """Record the vault's source metadata, then download the media it lists.

    The metadata phase stores its result before the download phase starts, so
    downloads that fail cost nothing but their own files. A catalog from an
    older version is upgraded on the way in, which also means downloads always
    work from a current-version catalog and its upgraded source URL.
    """
    vault_dir = Path(args.name)
    catalog, _ = load_catalog(vault_dir)
    changes = None if args.skip_metadata else _sync_metadata(vault_dir, catalog)
    if not args.skip_download:
        limits = {category: getattr(args, category) for category in CATEGORIES}
        download_assets(vault_dir, catalog, limits, args.format)
    if changes is not None:
        print(render_sync_summary(changes, vault_dir.name))


def _sync_metadata(vault_dir: Path, catalog: dict) -> ChangeSet:
    """Merge a fresh source snapshot into ``catalog`` and store it.

    Nothing is written until the whole snapshot has been fetched and
    validated, so a failing source leaves the vault untouched.
    """
    snapshot = fetch_source(catalog["source"])
    changes = merge_catalog(catalog, snapshot, datetime.now().replace(microsecond=0))
    save_catalog(vault_dir, catalog)
    return changes


def run_migrate(args: argparse.Namespace) -> None:
    """Store the vault's catalog in the current format.

    A vault that already uses it is left exactly as it is, backup included.
    """
    vault_dir = Path(args.name)
    catalog, upgraded = load_catalog(vault_dir)
    if upgraded:
        save_catalog(vault_dir, catalog)


def run_digest(args: argparse.Namespace) -> None:
    """Print what changed in a vault, in whatever version its catalog is stored.

    The catalog is read in its own layout and never written back, so a digest
    of an older vault leaves it older.
    """
    vault_dir = Path(args.name)
    view = read_view(vault_dir)
    moment = datetime.now().replace(microsecond=0)
    print(render_digest(view, collect_changes(view), vault_dir.name, moment))


def run_serve(args: argparse.Namespace) -> None:
    """Serve the vaults of the working directory and open a browser on them.

    The viewer reads each vault in its own version, so a version 1 or version
    2 vault is browsable without migrating it first.
    """
    serve(Path.cwd(), args.name, args.host, args.port)


def main(argv: list[str] | None = None) -> int:
    """Run a subcommand, reporting expected failures on stderr."""
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except (VaultError, SourceError, ServerError) as error:
        print(f"mvault: {error}", file=sys.stderr)
        return 1
    return 0

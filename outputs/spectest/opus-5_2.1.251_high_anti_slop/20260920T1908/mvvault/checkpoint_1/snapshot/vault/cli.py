"""Command line interface for mvault."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .catalog import CATEGORIES, VaultError, load_catalog, new_catalog, save_catalog
from .source import SourceError, fetch_source
from .sync import merge_category


def build_parser() -> argparse.ArgumentParser:
    """Define the ``init`` and ``sync`` subcommands."""
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and record tracked-field history.",
    )
    subcommands = parser.add_subparsers(dest="subcommand", metavar="<subcommand>", required=True)

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="vault directory to create")
    init.add_argument("url", help="source URL to record in the catalog")
    init.set_defaults(handler=run_init)

    sync = subcommands.add_parser("sync", help="record the current source metadata in a vault")
    sync.add_argument("name", help="vault directory to update")
    sync.set_defaults(handler=run_sync)
    return parser


def run_init(args: argparse.Namespace) -> None:
    """Create ``<name>/`` holding an empty catalog for ``<url>``."""
    vault_dir = Path(args.name)
    if vault_dir.exists():
        raise VaultError(f"vault '{args.name}' already exists")
    vault_dir.mkdir(parents=True)
    save_catalog(vault_dir, new_catalog(args.url))


def run_sync(args: argparse.Namespace) -> None:
    """Fetch the vault's source and merge the snapshot into its catalog.

    The catalog is only written once the whole snapshot has been fetched and
    validated, so a failing source leaves the vault untouched.
    """
    vault_dir = Path(args.name)
    catalog = load_catalog(vault_dir)
    snapshot = fetch_source(catalog["source"])
    moment = datetime.now().replace(microsecond=0)
    for category in CATEGORIES:
        merge_category(catalog[category], snapshot[category], moment)
    save_catalog(vault_dir, catalog)


def main(argv: list[str] | None = None) -> int:
    """Run a subcommand, reporting expected failures on stderr."""
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except (VaultError, SourceError) as error:
        print(f"mvault: {error}", file=sys.stderr)
        return 1
    return 0

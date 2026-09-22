"""Command line entry point for mvault.

mvault keeps a local vault of media-platform metadata and records how the
tracked fields of each entry change from one sync to the next.
"""

import argparse
import sys
from typing import Optional, Sequence

from errors import MvaultError
from vault import init_vault, sync_vault


def build_parser() -> argparse.ArgumentParser:
    """Assemble the ``init`` and ``sync`` command line."""
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init = subcommands.add_parser("init", help="create a new vault for a source URL")
    init.add_argument("name", help="directory of the vault to create")
    init.add_argument("url", help="source URL the vault tracks")
    init.set_defaults(run=lambda args: init_vault(args.name, args.url))

    sync = subcommands.add_parser("sync", help="record the current source state in a vault")
    sync.add_argument("name", help="directory of an existing vault")
    sync.set_defaults(run=lambda args: sync_vault(args.name))

    return parser


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

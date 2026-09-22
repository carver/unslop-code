#!/usr/bin/env python3
"""Query an XML document read from stdin with an XPath 1.0 expression."""

import argparse
import sys

from document import parse_document
from errors import XjqError
from query import evaluate
from render import render


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xjq.py", description=__doc__, allow_abbrev=False
    )
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; input is read from stdin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    args = _build_arg_parser().parse_args(argv)
    try:
        root = parse_document(sys.stdin.buffer.read())
        result = evaluate(root, args.query)
    except XjqError as exc:
        print(f"xjq.py: error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

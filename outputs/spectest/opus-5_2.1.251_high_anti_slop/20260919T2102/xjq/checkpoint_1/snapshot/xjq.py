#!/usr/bin/env python3
"""Query XML read from stdin with an XPath 1.0 expression."""

import argparse
import sys

from xjqlib.document import parse_document
from xjqlib.errors import XjqError
from xjqlib.query import evaluate
from xjqlib.rendering import render


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line arguments."""
    parser = argparse.ArgumentParser(prog="xjq.py", description=__doc__)
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression to evaluate")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility; the document is always read from stdin",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run a query and print its result, returning the process exit code."""
    args = parse_args(argv)
    try:
        document = parse_document(sys.stdin.buffer.read())
        output = render(evaluate(document, args.query))
    except XjqError as error:
        print(error, file=sys.stderr)
        return 1
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

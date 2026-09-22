#!/usr/bin/env python3
"""xjq — query XML read from stdin with an XPath 1.0 expression.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

The document always comes from stdin; INFILE is accepted for call-site
compatibility but never read.
"""

import argparse
import sys

from xjq_core import XjqError, evaluate, parse_document, render


def parse_args(argv):
    """Build the CLI argument namespace from `argv`."""
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query XML read from stdin with an XPath 1.0 expression.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression to evaluate")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; input is read from stdin",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Run one query and return the process exit code."""
    args = parse_args(argv)

    try:
        root = parse_document(sys.stdin.buffer.read())
        output = render(evaluate(root, args.query))
    except XjqError as exc:
        print(f"xjq: {exc}", file=sys.stderr)
        return 1

    if output is not None:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

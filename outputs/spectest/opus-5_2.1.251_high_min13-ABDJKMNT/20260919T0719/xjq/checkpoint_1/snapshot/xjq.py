#!/usr/bin/env python3
"""Evaluate an XPath 1.0 query against an XML document read from stdin."""

import argparse
import sys

from xjq_core.document import parse_document
from xjq_core.errors import XjqError
from xjq_core.query import evaluate
from xjq_core.render import render


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description=__doc__,
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression to evaluate")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility; the document is always read from stdin",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        document = parse_document(sys.stdin.buffer.read())
        output = render(evaluate(document, args.query))
    except XjqError as exc:
        print(f"xjq: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

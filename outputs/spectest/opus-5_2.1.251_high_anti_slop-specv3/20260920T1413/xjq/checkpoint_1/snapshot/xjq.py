#!/usr/bin/env python3
"""Query an XML or HTML document read from stdin with an XPath 1.0 expression."""

import argparse
import sys

from errors import XjqError
from render import render
from xml_input import parse_document
from xpath_query import evaluate


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line into a query and an ignored input file name."""
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Evaluate an XPath 1.0 query against the XML/HTML document on stdin.",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; the document is read from stdin",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Run the tool, returning the process exit code."""
    args = parse_args(argv)
    try:
        document = parse_document(sys.stdin.buffer.read())
        result = evaluate(document, args.query)
    except XjqError as exc:
        print(exc, file=sys.stderr)
        return 1
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

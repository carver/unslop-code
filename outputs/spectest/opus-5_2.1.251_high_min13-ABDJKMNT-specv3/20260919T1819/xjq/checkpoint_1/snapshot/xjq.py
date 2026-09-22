#!/usr/bin/env python3
"""Query the XML document on stdin with an XPath 1.0 expression."""

import argparse
import sys

from xjqlib.document import DocumentError, parse_document
from xjqlib.query import QueryError, evaluate
from xjqlib.render import render


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="xjq.py", description=__doc__, allow_abbrev=False
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility; input is always read from stdin",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        document = parse_document(sys.stdin.buffer.read())
        result = evaluate(document, args.query)
    except DocumentError as exc:
        print(f"xjq.py: unable to parse xml input: {exc}", file=sys.stderr)
        return 1
    except QueryError as exc:
        print(f"xjq.py: invalid xpath expression: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

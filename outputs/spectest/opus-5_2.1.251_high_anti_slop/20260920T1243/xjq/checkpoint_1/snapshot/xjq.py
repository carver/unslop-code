#!/usr/bin/env python3
"""Query an XML document read from stdin with an XPath 1.0 expression."""

import argparse
import sys

from render import render
from xmldoc import XmlInputError, XPathQueryError, evaluate, parse_document


def parse_args(argv):
    """Build the command line arguments for `xjq.py [OPTIONS] QUERY [INFILE]`."""
    parser = argparse.ArgumentParser(prog="xjq", description=__doc__)
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility; the document is always read from stdin",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Run the query against stdin and return the process exit code."""
    args = parse_args(argv)
    try:
        root = parse_document(sys.stdin.buffer.read())
        result = evaluate(root, args.query)
    except XmlInputError as exc:
        print(f"xjq: cannot parse xml input: {exc}", file=sys.stderr)
        return 1
    except XPathQueryError as exc:
        print(f"xjq: invalid xpath expression {args.query!r}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

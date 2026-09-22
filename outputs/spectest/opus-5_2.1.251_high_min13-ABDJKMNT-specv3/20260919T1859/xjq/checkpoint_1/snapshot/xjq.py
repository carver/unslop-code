#!/usr/bin/env python3
"""Query XML read from stdin with an XPath 1.0 expression.

Usage: ``python xjq.py [OPTIONS] QUERY [INFILE]``. Matching text and attribute
values are printed one per line; a matching element is pretty-printed as XML.
"""

import argparse
import sys

from xjqlib.errors import XjqError
from xjqlib.formatting import format_result
from xjqlib.parsing import parse_document
from xjqlib.query import evaluate


def parse_args(argv):
    """Build the command line: a required query and an ignored input path."""
    parser = argparse.ArgumentParser(prog="xjq.py", description=__doc__)
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; input is read from stdin",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Run one query against stdin, returning the process exit code."""
    args = parse_args(argv)
    try:
        document = parse_document(sys.stdin.buffer.read())
        payload = format_result(evaluate(document, args.query))
    except XjqError as error:
        print(f"xjq.py: {error}", file=sys.stderr)
        return 1
    # Written as bytes so the document's characters survive any stdout locale.
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

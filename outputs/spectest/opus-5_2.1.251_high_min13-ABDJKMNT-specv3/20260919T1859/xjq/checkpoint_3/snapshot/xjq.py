#!/usr/bin/env python3
"""Query XML or JSON read from stdin with an XPath 1.0 expression or CSS selector.

Stdin is auto-detected: a JSON object or array is converted to XML under a
``<root>`` element that records each value's JSON type, and anything else is
parsed as XML/HTML.

Usage: ``python xjq.py [OPTIONS] QUERY [INFILE]``. Matching text and attribute
values are printed one per line; a matching element is pretty-printed as XML,
unless a text-extraction flag or the ``::text`` pseudo-element asks for its
text instead.
"""

import argparse
import sys

from xjqlib.css import translate_selector
from xjqlib.errors import XjqError
from xjqlib.formatting import format_result
from xjqlib.parsing import parse_document
from xjqlib.query import evaluate
from xjqlib.text import requested_mode


def parse_args(argv):
    """Build the command line: a query, its mode flags, and an ignored path."""
    parser = argparse.ArgumentParser(prog="xjq.py", description=__doc__)
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; input is read from stdin",
    )
    parser.add_argument(
        "--css", action="store_true", help="interpret QUERY as a CSS selector"
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="print the direct text of each matched element",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="print the descendant text of each matched element; wins over --text",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Run one query against stdin, returning the process exit code."""
    args = parse_args(argv)
    try:
        document = parse_document(sys.stdin.buffer.read())
        expression = translate_selector(args.query) if args.css else args.query
        extraction = requested_mode(args.text, args.text_all)
        payload = format_result(evaluate(document, expression), extraction)
    except XjqError as error:
        print(f"xjq.py: {error}", file=sys.stderr)
        return 1
    # Written as bytes so the document's characters survive any stdout locale.
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

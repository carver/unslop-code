#!/usr/bin/env python3
"""Query an XML or JSON document with an XPath 1.0 expression or CSS selector.

The document comes from ``INFILE`` when one is named and from stdin otherwise,
and its kind is auto-detected: a JSON object or array is converted to XML under
a ``<root>`` element that records each value's JSON type, and anything else is
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
from xjqlib.formatting import OutputOptions, format_result
from xjqlib.parsing import parse_document
from xjqlib.query import evaluate
from xjqlib.source import read_source
from xjqlib.text import requested_mode


def parse_args(argv):
    """Build the command line: a query, its input path, and the mode flags."""
    parser = argparse.ArgumentParser(prog="xjq.py", description=__doc__)
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="file to read instead of stdin",
    )
    parser.add_argument(
        "ignored",
        metavar="...",
        nargs="*",
        help="further positional arguments, accepted and ignored",
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
    parser.add_argument(
        "-f", "--first", action="store_true", help="return only the first result"
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize XML without added pretty-print formatting",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Run one query against the chosen input, returning the process exit code."""
    args = parse_args(argv)
    try:
        document = parse_document(read_source(args.infile))
        expression = translate_selector(args.query) if args.css else args.query
        extraction = requested_mode(args.text, args.text_all)
        options = OutputOptions(first=args.first, compact=args.compact)
        payload = format_result(evaluate(document, expression), extraction, options)
    except XjqError as error:
        print(f"xjq.py: {error}", file=sys.stderr)
        return 1
    # Written as bytes so the document's characters survive any stdout locale.
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

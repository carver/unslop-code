#!/usr/bin/env python3
"""Query the XML, HTML or JSON document on stdin with XPath 1.0 or a CSS selector."""

import argparse
import sys

from xjqlib.css import CssError, translate
from xjqlib.document import DocumentError, parse_document
from xjqlib.json_input import JsonKeyError
from xjqlib.query import QueryError, evaluate
from xjqlib.render import render
from xjqlib.text import TextMode, extract, mode_from_flags

_MESSAGES = {
    DocumentError: "unable to parse xml input",
    CssError: "invalid css selector",
    QueryError: "invalid xpath expression",
    JsonKeyError: "invalid json key",
}


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
        help="print the descendant text of each matched element",
    )
    return parser.parse_args(argv)


def build_query(args) -> tuple[str, TextMode]:
    """Return the XPath to evaluate and the text mode to apply to its result.

    A ``::text`` pseudo-element in a CSS query states the mode itself, which
    leaves the text flags as no-op modifiers.
    """
    flag_mode = mode_from_flags(args.text, args.text_all)
    if not args.css:
        return args.query, flag_mode
    query, query_mode = translate(args.query)
    return query, flag_mode if query_mode is TextMode.NONE else query_mode


def run(args) -> str:
    """Return the stdout text for the query in ``args`` against stdin."""
    document = parse_document(sys.stdin.buffer.read())
    query, mode = build_query(args)
    return render(extract(evaluate(document, query), mode))


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        output = run(args)
    except (DocumentError, CssError, QueryError, JsonKeyError) as exc:
        print(f"xjq.py: {_MESSAGES[type(exc)]}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

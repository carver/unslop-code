#!/usr/bin/env python3
"""Query an XML, HTML or JSON document with XPath 1.0 or a CSS selector.

The document is read from INFILE when given, otherwise from stdin.
"""

import argparse
import sys

from xjqlib.css import CssError, translate
from xjqlib.document import DocumentError, parse_document
from xjqlib.json_input import JsonKeyError
from xjqlib.query import QueryError, evaluate
from xjqlib.render import render
from xjqlib.source import SourceError, read_source
from xjqlib.text import TextMode, extract, mode_from_flags

_MESSAGES = {
    DocumentError: "unable to parse xml input",
    CssError: "invalid css selector",
    QueryError: "invalid xpath expression",
    JsonKeyError: "invalid json key",
    SourceError: "unable to read input file",
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
        help="document to query; defaults to stdin",
    )
    parser.add_argument("ignored", metavar="ARGS", nargs="*", help=argparse.SUPPRESS)
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
    parser.add_argument(
        "-f", "--first", action="store_true", help="print only the first result"
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize xml results without pretty-print formatting",
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
    """Return the stdout text for the query in ``args`` against its input."""
    document = parse_document(read_source(args.infile))
    query, mode = build_query(args)
    results = extract(evaluate(document, query), mode)
    return render(results, first=args.first, compact=args.compact)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        output = run(args)
    except (DocumentError, CssError, QueryError, JsonKeyError, SourceError) as exc:
        print(f"xjq.py: {_MESSAGES[type(exc)]}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

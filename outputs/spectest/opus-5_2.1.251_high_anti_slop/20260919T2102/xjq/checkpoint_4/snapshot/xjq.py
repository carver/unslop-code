#!/usr/bin/env python3
"""Query XML, HTML or JSON read from a file or stdin with an XPath 1.0 expression or a CSS selector."""

import argparse
import sys

from xjqlib.css import css_to_xpath
from xjqlib.document import parse_document
from xjqlib.errors import XjqError
from xjqlib.query import evaluate
from xjqlib.rendering import render
from xjqlib.source import read_input
from xjqlib.text import TextMode, extract_text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line arguments."""
    parser = argparse.ArgumentParser(prog="xjq.py", description=__doc__)
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression, or CSS selector when --css is given")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="file to read the document from; stdin is used when it is left out",
    )
    parser.add_argument("ignored", metavar="...", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument(
        "--css", action="store_true", help="interpret QUERY as a CSS selector"
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="print the direct text of the matched elements",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="print the descendant text of the matched elements; wins over --text",
    )
    parser.add_argument(
        "-f", "--first", action="store_true", help="print only the first result"
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="print XML results without the added indentation",
    )
    return parser.parse_args(argv)


def text_mode(args: argparse.Namespace) -> TextMode:
    """Pick the text extraction mode the flags ask for, ``--text-all`` first."""
    if args.text_all:
        return TextMode.DESCENDANT
    return TextMode.DIRECT if args.text else TextMode.NONE


def main(argv: list[str] | None = None) -> int:
    """Run a query and print its result, returning the process exit code."""
    args = parse_args(argv)
    try:
        expression = css_to_xpath(args.query) if args.css else args.query
        document = parse_document(read_input(args.infile))
        result = extract_text(evaluate(document, expression), text_mode(args))
        output = render(result, first=args.first, compact=args.compact)
    except XjqError as error:
        print(error, file=sys.stderr)
        return 1
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

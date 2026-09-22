#!/usr/bin/env python3
"""Query an XML document read from stdin with an XPath 1.0 or CSS expression."""

import argparse
import sys

from css import translate
from document import parse_document
from errors import XjqError
from query import evaluate
from render import render
from text import TextMode, extract, extracts_text


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xjq.py", description=__doc__, allow_abbrev=False
    )
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression, or a CSS selector with --css")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; input is read from stdin",
    )
    parser.add_argument(
        "--css", action="store_true", help="read QUERY as a CSS selector instead"
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="print the direct text of each matched element, one per line",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="print the descendant text of each matched element, one per line",
    )
    return parser


def _text_mode(args: argparse.Namespace) -> TextMode | None:
    """Return the text extraction the flags ask for, or None if they ask none.

    ``--text-all`` outranks ``--text``, and neither adds anything to a query
    that already selects text.
    """
    if extracts_text(args.query):
        return None
    if args.text_all:
        return TextMode.DESCENDANT
    if args.text:
        return TextMode.DIRECT
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    args = _build_arg_parser().parse_args(argv)
    try:
        expression = translate(args.query) if args.css else args.query
        root = parse_document(sys.stdin.buffer.read())
        result = evaluate(root, expression)
        mode = _text_mode(args)
        if mode is not None:
            result = extract(result, mode)
    except XjqError as exc:
        print(f"xjq.py: error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

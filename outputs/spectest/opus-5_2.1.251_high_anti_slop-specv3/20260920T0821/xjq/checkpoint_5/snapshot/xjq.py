#!/usr/bin/env python3
"""Query an XML or JSON document with an XPath 1.0 or CSS expression."""

import argparse
import sys

from css import translate
from document import parse_document, read_source
from errors import XjqError
from json_export import export, exportable
from query import Result, evaluate, is_union
from render import render
from text import TextMode, extract, extracts_text, merge


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xjq.py", description=__doc__, allow_abbrev=False
    )
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression, or a CSS selector with --css")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="file to query instead of stdin",
    )
    parser.add_argument("ignored", metavar="...", nargs="*", help=argparse.SUPPRESS)
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
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="export matched elements as JSON objects of tag name and text",
    )
    parser.add_argument(
        "-f", "--first", action="store_true", help="print only the first result"
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize XML results without pretty-print formatting",
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


def _format(args: argparse.Namespace, result: Result) -> str:
    """Return the stdout text for ``result`` under the output flags.

    The flags rank ``--text-all`` above ``--text``, both above ``--json``, and
    all of them above the default formatting, which picks its layout from the
    result itself. ``--json`` exports matched elements only, so it does nothing
    for a result that is already text, and nothing in CSS mode, where the output
    follows the rules of the selector.
    """
    mode = _text_mode(args)
    if mode is not None:
        result = _texts(args, result, mode)
    elif args.json and not args.css and exportable(result):
        return export(result, first=args.first, compact=args.compact)
    return render(result, first=args.first, compact=args.compact)


def _texts(args: argparse.Namespace, result: Result, mode: TextMode) -> Result:
    """Extract the text of the matched elements the way ``mode`` says.

    The descendant text of an XPath union is concatenated into one string, since
    its paths read parts of the same document rather than separate matches.
    """
    texts = extract(result, mode)
    if mode is TextMode.DESCENDANT and not args.css and is_union(args.query):
        return merge(texts, first=args.first)
    return texts


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    args = _build_arg_parser().parse_args(argv)
    try:
        expression = translate(args.query) if args.css else args.query
        root = parse_document(read_source(args.infile))
        output = _format(args, evaluate(root, expression))
    except XjqError as exc:
        print(f"xjq.py: error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

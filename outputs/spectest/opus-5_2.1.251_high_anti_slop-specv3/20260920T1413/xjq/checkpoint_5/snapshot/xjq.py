#!/usr/bin/env python3
"""Query a JSON, XML or HTML document with XPath 1.0 or CSS selectors."""

import argparse
import sys

from css_query import evaluate_css
from document_input import parse_document
from errors import XjqError
from input_source import read_input
from json_export import export_json
from render import is_element_list, render
from text_extract import TextMode, extract_text, join_text
from xpath_query import evaluate, is_union


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line into a query, an optional input file, and the flags.

    Positional arguments after QUERY and INFILE are accepted and ignored.
    """
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description=(
            "Evaluate an XPath 1.0 or CSS query against INFILE, or against the document on "
            "stdin, which may be XML, HTML, or JSON converted into a <root> element."
        ),
    )
    parser.add_argument("query", metavar="QUERY", help="XPath 1.0 expression, or CSS selector with --css")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="UTF-8 document to query; stdin is read when it is omitted",
    )
    parser.add_argument("ignored", metavar="ARG", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--css", action="store_true", help="interpret QUERY as a CSS selector")
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="print the direct text of each matched element",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="print the text of each matched element and all of its descendants",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="print the matched elements as a JSON array of {tag: text} objects",
    )
    parser.add_argument("-f", "--first", action="store_true", help="print only the first result")
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize XML output without added pretty-print formatting",
    )
    return parser.parse_args(argv)


def text_mode(args: argparse.Namespace):
    """Return the ``TextMode`` the flags ask for, or ``None``.

    ``--text-all`` wins over ``--text`` when both are given.
    """
    if args.text_all:
        return TextMode.DESCENDANT
    if args.text:
        return TextMode.DIRECT
    return None


def format_result(result, args: argparse.Namespace) -> str:
    """Return the stdout text for ``result``, following the output flag precedence.

    The text flags come first, then ``--json``, then the auto-formatting of
    ``render``. Both only reshape matched elements: a query that produces text
    of its own -- ``text()``, an attribute, a union that mixes text with
    elements -- is written as text whatever the flags say, and ``--json`` is
    reserved for XPath queries, as CSS output follows the rules of the query.
    """
    mode = text_mode(args)
    if is_element_list(result):
        matches = result[:1] if args.first else result
        if mode is TextMode.DESCENDANT and not args.css and is_union(args.query):
            return join_text(matches)
        if mode is not None:
            result = extract_text(result, mode)
        elif args.json and not args.css:
            return export_json(matches, compact=args.compact)
    return render(result, first=args.first, compact=args.compact)


def main(argv=None) -> int:
    """Run the tool, returning the process exit code."""
    args = parse_args(argv)
    try:
        document = parse_document(read_input(args.infile))
        if args.css:
            result = evaluate_css(document, args.query)
        else:
            result = evaluate(document, args.query)
    except XjqError as exc:
        print(exc, file=sys.stderr)
        return 1
    sys.stdout.write(format_result(result, args))
    return 0


if __name__ == "__main__":
    sys.exit(main())

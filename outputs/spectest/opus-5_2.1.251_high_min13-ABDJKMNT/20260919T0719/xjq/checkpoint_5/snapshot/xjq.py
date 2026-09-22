#!/usr/bin/env python3
"""Evaluate an XPath 1.0 or CSS query against an XML or JSON document."""

import argparse
import sys

from xjq_core.css import compile_query
from xjq_core.document import parse_document
from xjq_core.errors import XjqError
from xjq_core.output import OutputOptions, present
from xjq_core.query import evaluate
from xjq_core.source import read_source
from xjq_core.text import TextMode
from xjq_core.union import is_union


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description=__doc__,
    )
    parser.add_argument(
        "query",
        metavar="QUERY",
        help="XPath expression, or CSS selector when --css is given",
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="document to query; stdin is used when it is omitted",
    )
    parser.add_argument(
        "ignored",
        metavar="IGNORED",
        nargs="*",
        help="further positional arguments, which are ignored",
    )
    parser.add_argument(
        "-f",
        "--first",
        action="store_true",
        help="return only the first result",
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize xml without added pretty-print formatting",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="export matched xml elements as json",
    )
    parser.add_argument(
        "--css",
        action="store_true",
        help="interpret QUERY as a CSS selector",
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
        help="print the descendant text of each matched element; beats --text",
    )
    return parser.parse_args(argv)


def resolve_query(args: argparse.Namespace) -> tuple[str, TextMode | None]:
    """Turn the arguments into an XPath expression and the text mode to apply.

    A `::text` pseudo-element states its own mode, which is why the text flags
    are no-op modifiers for a query that uses one.
    """
    if not args.css:
        return args.query, flag_text_mode(args)
    expression, mode = compile_query(args.query)
    return expression, mode or flag_text_mode(args)


def flag_text_mode(args: argparse.Namespace) -> TextMode | None:
    """Read the text mode the flags ask for, `--text-all` outranking `--text`."""
    if args.text_all:
        return TextMode.DESCENDANT
    if args.text:
        return TextMode.DIRECT
    return None


def output_options(args: argparse.Namespace, mode: TextMode | None) -> OutputOptions:
    """Collect the output flags, dropping the ones CSS mode does not honour.

    `--json` has no effect in CSS mode, and neither does the union handling of
    `--text-all`: a CSS selector list translates to an XPath union, but the
    query the user wrote is a list rather than a union of paths.
    """
    return OutputOptions(
        text_mode=mode,
        union=not args.css and is_union(args.query),
        json=args.json and not args.css,
        first=args.first,
        compact=args.compact,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        document = parse_document(read_source(args.infile))
        expression, mode = resolve_query(args)
        result = evaluate(document, expression, args.query if args.css else None)
        output = present(result, output_options(args, mode))
    except XjqError as exc:
        print(f"xjq: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

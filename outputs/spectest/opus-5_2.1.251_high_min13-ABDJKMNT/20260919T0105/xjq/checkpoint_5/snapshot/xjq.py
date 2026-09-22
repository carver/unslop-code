#!/usr/bin/env python3
"""xjq — query XML with an XPath 1.0 expression or CSS selector.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

The document comes from INFILE when one is named and from stdin otherwise.
"""

import argparse
import sys

from xjq_core import (
    DESCENDANT,
    DIRECT,
    CssSelectorError,
    OutputOptions,
    XjqError,
    XPathQueryError,
    css_to_xpath,
    evaluate,
    extracts_text,
    format_results,
    is_union,
    parse_document,
    read_document,
)


def parse_args(argv):
    """Build the CLI argument namespace from `argv`."""
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query an XML or JSON document with XPath 1.0 or a CSS selector.",
    )
    parser.add_argument(
        "--css",
        action="store_true",
        help="interpret QUERY as a CSS selector, which may end in ::text",
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="extract the direct text of each matched element",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="extract the descendant text of each matched element; wins over --text",
    )
    parser.add_argument(
        "-f",
        "--first",
        action="store_true",
        help="return only the first result",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="export matched elements as JSON; the text flags outrank it",
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize XML output without added pretty-print formatting",
    )
    parser.add_argument("query", metavar="QUERY", help="XPath expression or CSS selector")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="document to query; stdin is read when this is omitted",
    )
    parser.add_argument(
        "ignored",
        metavar="ARGS",
        nargs="*",
        help="further positional arguments, which are ignored",
    )
    return parser.parse_args(argv)


def output_options(args):
    """Resolve the output flags into the options the formatting stage takes.

    `--text-all` outranks `--text`, which outranks `--json`. The text flags
    become no-ops when the query already extracts text, and unions and `--json`
    are XPath-mode features, so a CSS query takes part in neither.
    """
    xpath = None if args.css else args.query
    text_mode = DESCENDANT if args.text_all else DIRECT if args.text else None
    return OutputOptions(
        text_mode=None if xpath and extracts_text(xpath) else text_mode,
        json_export=args.json and not args.css and text_mode is None,
        first=args.first,
        compact=args.compact,
        union=bool(xpath) and is_union(xpath),
    )


def main(argv=None):
    """Run one query and return the process exit code."""
    args = parse_args(argv)

    try:
        root = parse_document(read_document(args.infile, sys.stdin.buffer))
        expression = css_to_xpath(args.query) if args.css else args.query
        failure = CssSelectorError if args.css else XPathQueryError
        output = format_results(
            evaluate(root, expression, failure=failure), output_options(args)
        )
    except XjqError as exc:
        print(f"xjq: {exc}", file=sys.stderr)
        return 1

    if output is not None:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

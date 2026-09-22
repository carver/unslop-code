#!/usr/bin/env python3
"""xjq — query XML read from stdin with an XPath 1.0 expression or CSS selector.

Usage: python xjq.py [OPTIONS] QUERY [INFILE]

The document always comes from stdin; INFILE is accepted for call-site
compatibility but never read.
"""

import argparse
import sys

from xjq_core import (
    DESCENDANT,
    DIRECT,
    XjqError,
    css_to_xpath,
    evaluate,
    extract_text,
    parse_document,
    render,
)


def parse_args(argv):
    """Build the CLI argument namespace from `argv`."""
    parser = argparse.ArgumentParser(
        prog="xjq.py",
        description="Query XML read from stdin with XPath 1.0 or a CSS selector.",
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
    parser.add_argument("query", metavar="QUERY", help="XPath expression or CSS selector")
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="accepted for compatibility and ignored; input is read from stdin",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Run one query and return the process exit code."""
    args = parse_args(argv)
    mode = DESCENDANT if args.text_all else DIRECT if args.text else None

    try:
        root = parse_document(sys.stdin.buffer.read())
        expression = css_to_xpath(args.query) if args.css else args.query
        output = render(extract_text(evaluate(root, expression), mode))
    except XjqError as exc:
        print(f"xjq: {exc}", file=sys.stderr)
        return 1

    if output is not None:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

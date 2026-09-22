#!/usr/bin/env python3
"""Query a JSON or XML document read from a file or stdin with an XPath 1.0 or CSS expression."""

import argparse
import sys

import docinput
import jsondoc
import textnodes
import xmldoc
from cssquery import CssQueryError, translate
from render import render


def parse_args(argv):
    """Build the command line arguments for `xjq.py [OPTIONS] QUERY [INFILE]`."""
    parser = argparse.ArgumentParser(prog="xjq", description=__doc__)
    parser.add_argument(
        "query", metavar="QUERY", help="XPath 1.0 expression, or CSS selector with --css"
    )
    parser.add_argument(
        "infile",
        metavar="INFILE",
        nargs="?",
        help="file to read the document from; stdin is used without it",
    )
    # Trailing positional arguments are accepted and ignored rather than rejected.
    parser.add_argument("ignored", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument(
        "--css", action="store_true", help="interpret QUERY as a CSS selector"
    )
    parser.add_argument(
        "-f", "--first", action="store_true", help="print only the first result"
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="serialize matched elements without pretty-printing them",
    )
    parser.add_argument(
        "-t",
        "--text",
        action="store_true",
        help="print the text directly below each matched element",
    )
    parser.add_argument(
        "--text-all",
        action="store_true",
        help="print every text node below each matched element; wins over --text",
    )
    return parser.parse_args(argv)


def resolve_query(args):
    """Return the XPath to evaluate and the text mode to apply to its result."""
    if not args.css:
        return args.query, _flag_mode(args)
    query, mode = translate(args.query)
    return query, _flag_mode(args) if mode is None else mode


def _flag_mode(args):
    """Return the text mode the flags ask for, `--text-all` winning over `--text`."""
    if args.text_all:
        return textnodes.ALL
    if args.text:
        return textnodes.DIRECT
    return None


def parse_input(data):
    """Parse `data` (bytes) as JSON when it looks like JSON, and as XML otherwise."""
    root = jsondoc.parse_document(data)
    if root is None:
        return xmldoc.parse_document(data)
    return root


def main(argv=None):
    """Run the query against the chosen input and return the process exit code."""
    args = parse_args(argv)
    try:
        query, mode = resolve_query(args)
        root = parse_input(docinput.read_document(args.infile))
        result = xmldoc.evaluate(root, query)
    except CssQueryError as exc:
        print(f"xjq: invalid css selector {args.query!r}: {exc}", file=sys.stderr)
        return 1
    except docinput.InputReadError as exc:
        print(f"xjq: cannot read {args.infile!r}: {exc}", file=sys.stderr)
        return 1
    except jsondoc.JsonInputError as exc:
        print(f"xjq: invalid json key: {exc}", file=sys.stderr)
        return 1
    except xmldoc.XmlInputError as exc:
        print(f"xjq: cannot parse xml input: {exc}", file=sys.stderr)
        return 1
    except xmldoc.XPathQueryError as exc:
        print(f"xjq: invalid xpath expression {args.query!r}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(
        render(textnodes.extract(result, mode), args.first, args.compact)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

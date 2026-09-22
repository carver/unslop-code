#!/usr/bin/env python3
"""Merge multiple CSV files into a single globally sorted CSV."""
from __future__ import annotations

import sys

from csvmerge.cli import parse_args
from csvmerge.errors import MergeError
from csvmerge.pipeline import run


def main(argv: list[str] | None = None) -> int:
    options = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        run(options)
    except (MergeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

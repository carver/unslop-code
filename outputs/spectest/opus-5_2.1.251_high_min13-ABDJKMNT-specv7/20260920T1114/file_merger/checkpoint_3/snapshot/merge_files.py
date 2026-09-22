#!/usr/bin/env python3
"""Merge CSV, TSV, JSON Lines and Parquet files into one sorted CSV.

See README.md for the supported options; the work itself lives in the csvmerge
package.
"""

from __future__ import annotations

import sys

from csvmerge.cli import parse_args
from csvmerge.errors import MergeError
from csvmerge.pipeline import run


def main(argv: list[str] | None = None) -> int:
    """Run the tool, reporting user-facing errors on stderr."""
    try:
        run(parse_args(sys.argv[1:] if argv is None else argv))
    except MergeError as error:
        print(f"merge_files.py: error: {error}", file=sys.stderr)
        return error.code
    return 0


if __name__ == "__main__":
    sys.exit(main())

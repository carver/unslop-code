#!/usr/bin/env python3
"""Merge multiple CSVs into one schema-aligned, globally sorted CSV.

Usage is documented by ``python merge_files.py --help``; the implementation
lives in the ``csvmerge`` package next to this script.
"""

import sys

from csvmerge.cli import main

if __name__ == "__main__":
    sys.exit(main())

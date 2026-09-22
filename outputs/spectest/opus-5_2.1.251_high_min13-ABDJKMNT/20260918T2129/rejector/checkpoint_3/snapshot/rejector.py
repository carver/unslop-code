#!/usr/bin/env python3
"""CLI entry point: run a generation task over a JSONL input file."""

import sys

from rejector_core.cli import main

if __name__ == "__main__":
    sys.exit(main())

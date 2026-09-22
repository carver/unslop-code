#!/usr/bin/env python3
"""Entry point: `python mvault.py <subcommand> [args...]`."""

import sys

from mvaultlib.cli import main

if __name__ == "__main__":
    sys.exit(main())

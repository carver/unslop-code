#!/usr/bin/env python3
"""Entry point for mvault: ``python mvault.py <subcommand> [args...]``."""

import sys

from vault.cli import main

if __name__ == "__main__":
    sys.exit(main())

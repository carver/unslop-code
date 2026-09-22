#!/usr/bin/env python3
"""CLI for running a YAML-configured generation task over a JSONL input file."""

from __future__ import annotations

import sys

from taskrunner.cli import main

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CLI for running YAML-configured generation tasks over JSONL input files."""

from __future__ import annotations

import sys

from taskrunner.cli import main

if __name__ == "__main__":
    sys.exit(main())

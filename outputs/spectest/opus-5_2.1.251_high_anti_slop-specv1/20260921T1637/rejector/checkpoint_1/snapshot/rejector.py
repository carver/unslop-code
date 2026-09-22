"""Entry point for the rejector task runner.

Usage:
    python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
"""

import sys

from cli import main

if __name__ == "__main__":
    sys.exit(main())

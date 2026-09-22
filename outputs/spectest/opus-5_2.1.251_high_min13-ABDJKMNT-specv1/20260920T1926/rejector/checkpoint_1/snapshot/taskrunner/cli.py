"""Command line entry point: argument parsing and run orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from .config import ConfigError, load_config
from .jsonl import read_rows, write_records
from .prompts import validate_rows
from .records import build_record, build_summary
from .runner import execute

# CLI flags that override the matching config value when given.
OVERRIDE_FLAGS = ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n")


class _Parser(argparse.ArgumentParser):
    """Argparse variant that reports usage errors with the spec's exit code 1."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise SystemExit(f"{self.prog}: error: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rejector.py")
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    run = subcommands.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument(
        "--scheme",
        choices=("greedy", "sample", "rejection"),
        help="override generation.scheme",
    )
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config, {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS})
        rows = read_rows(args.input)
        validate_rows(rows, config)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    outcomes, elapsed = asyncio.run(execute(config, rows))
    records = [
        build_record(row, outcome, config) for row, outcome in zip(rows, outcomes)
    ]
    write_records(args.output, records)
    print(json.dumps(build_summary(outcomes, elapsed)))
    return 0

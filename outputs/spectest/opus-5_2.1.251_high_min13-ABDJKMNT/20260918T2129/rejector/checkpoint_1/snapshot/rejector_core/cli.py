"""Argument parsing and the `run` command."""

from __future__ import annotations

import argparse
import json
import sys

from .config import SCHEMES, load_config
from .dataset import load_rows
from .errors import RejectorError
from .prompts import required_fields, validate_rows
from .reporting import build_summary, write_rows
from .runner import run_task


class _ArgumentParser(argparse.ArgumentParser):
    """Reports usage problems with exit code 1, the spec's error code."""

    def error(self, message: str):
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="rejector.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file")
    run.add_argument("--api-url", dest="api_url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--max-tokens", dest="max_tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", choices=SCHEMES, help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    overrides = {
        key: getattr(args, key)
        for key in ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n")
    }
    try:
        task = load_config(args.config, overrides)
        rows = load_rows(args.input)
        validate_rows(rows, required_fields(task))
    except RejectorError as exc:
        print(exc, file=sys.stderr)
        return 1

    outcomes, stats = run_task(task, rows)
    write_rows(args.output, outcomes, task.output_field)
    print(json.dumps(build_summary(outcomes, stats)))
    return 0

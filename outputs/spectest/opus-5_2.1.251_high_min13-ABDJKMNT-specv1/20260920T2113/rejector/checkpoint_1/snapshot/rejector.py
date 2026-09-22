"""CLI entry point: run a YAML task over a JSONL input file."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from rejlib.config import SCHEMES, load_config
from rejlib.errors import ConfigError
from rejlib.jsonl import read_rows, write_rows
from rejlib.prompts import validate_rows
from rejlib.runner import build_summary, process_rows

OVERRIDES = ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rejector.py", description="Run a generation task over a JSONL input file."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a task and write one result per input row")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file, created or overwritten")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--max-tokens", type=int, help="override task.generation.max_tokens")
    run.add_argument("--scheme", choices=SCHEMES, help="override task.generation.scheme")
    run.add_argument("--temperature", type=float, help="override task.generation.temperature")
    run.add_argument("--n", type=int, help="override task.generation.n")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config, {name: getattr(args, name) for name in OVERRIDES})
        rows = read_rows(args.input)
        validate_rows(rows, config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results, stats = asyncio.run(process_rows(config, rows))
    write_rows(args.output, results)
    print(json.dumps(build_summary(results, stats)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

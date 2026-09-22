"""CLI entry point: `python rejector.py run --config ... --input ... --output ...`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from config import SCHEMES, load_config
from errors import UsageError
from evaluation import require_answer_fields
from jsonl import read_jsonl, write_jsonl
from prompts import render_all
from runner import run_task, summarize

OVERRIDE_FLAGS = ("api_url", "model", "rpm", "scheme", "temperature", "max_tokens", "n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rejector", description="Run a prompt task against an OpenAI compatible API."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="execute a task over a JSONL input file")
    run.add_argument("--config", type=Path, required=True, help="YAML task config")
    run.add_argument("--input", type=Path, required=True, help="JSONL input file")
    run.add_argument("--output", type=Path, required=True, help="JSONL output file (overwritten)")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--scheme", choices=SCHEMES, help="override task.generation.scheme")
    run.add_argument("--temperature", type=float, help="override task.generation.temperature")
    run.add_argument("--max-tokens", type=int, help="override task.generation.max_tokens")
    run.add_argument("--n", type=int, help="override task.generation.n")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config, {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS})
        rows = read_jsonl(args.input)
        messages = render_all(config.prompt, rows)
        require_answer_fields(config.evaluation, rows)
        records, stats = asyncio.run(run_task(config, rows, messages))
        write_jsonl(args.output, records)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summarize(records, stats)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CLI entry point: run a YAML-configured generation task over a JSONL file."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from config import GENERATION_OVERRIDES, SCHEMES, TASK_OVERRIDES, load_config
from dataset import load_rows, prepare_prompts, write_results
from errors import TaskError
from runner import run_task


def main(argv: list[str] | None = None) -> int:
    """Return the process exit code: 0 on success, 1 on config or input errors."""
    args = _parse_args(argv)
    try:
        config = load_config(args.config, _overrides(args))
        rows = load_rows(args.input)
        prompts = prepare_prompts(rows, config)
    except TaskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    records, summary = asyncio.run(run_task(config, rows, prompts))
    write_results(args.output, records)
    print(json.dumps(summary))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rejector.py", description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run a task over an input file")
    run.add_argument("--config", required=True, help="path to the YAML task config")
    run.add_argument("--input", required=True, help="path to the JSONL input file")
    run.add_argument("--output", required=True, help="path to the JSONL output file")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--max-tokens", type=int, help="override task.generation.max_tokens")
    run.add_argument("--scheme", help=f"override task.generation.scheme ({'|'.join(SCHEMES)})")
    run.add_argument("--temperature", type=float, help="override task.generation.temperature")
    run.add_argument("--n", type=int, help="override task.generation.n")
    return parser.parse_args(argv)


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Collect the flags that were actually given, keyed by config field name."""
    supplied = vars(args)
    return {key: supplied[key] for key in TASK_OVERRIDES + GENERATION_OVERRIDES if supplied[key] is not None}


if __name__ == "__main__":
    sys.exit(main())

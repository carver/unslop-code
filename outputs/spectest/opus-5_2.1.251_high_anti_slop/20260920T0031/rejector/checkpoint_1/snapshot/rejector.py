#!/usr/bin/env python3
"""CLI for running a prompt task over a JSONL dataset.

Usage: python rejector.py run --config task.yaml --input data.jsonl --output results.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any, NoReturn

import httpx
import yaml

from config import SCHEMES, load_task_config
from dataset import load_rows, prepare_messages, write_results
from errors import RejectorError
from runner import run_task

#: Flags that replace the matching config value when provided.
OVERRIDE_FLAGS = ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n")


class Parser(argparse.ArgumentParser):
    """Argument parser that reports usage problems with the configuration exit code."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="rejector.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="path to the YAML task config")
    run.add_argument("--input", required=True, help="path to the JSONL input file")
    run.add_argument("--output", required=True, help="path to the JSONL output file")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", choices=sorted(SCHEMES), help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides: dict[str, Any] = {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS}
    try:
        task = load_task_config(args.config, overrides)
        rows = load_rows(args.input)
        prompts = prepare_messages(rows, task)
        results, summary = asyncio.run(run_task(task, rows, prompts))
        write_results(args.output, results)
    except (RejectorError, OSError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"error: API request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())

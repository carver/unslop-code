"""Command line interface: argument parsing and the top-level ``run`` flow."""

import argparse
import asyncio
import json
import sys
from typing import NoReturn

from config import load_task_config
from dataset import build_prompts, load_rows
from errors import UserError
from pipeline import run_task

#: CLI flags that override the matching config values when provided.
OVERRIDE_FLAGS = ("api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n")


class _Parser(argparse.ArgumentParser):
    """Parser that routes usage errors through the tool's exit-code-1 error path."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        raise UserError(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``rejector.py`` argument parser."""
    parser = _Parser(prog="rejector.py", description="Run a generation task against a chat completions API.")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, help="YAML task configuration")
    run.add_argument("--input", required=True, help="JSONL input file")
    run.add_argument("--output", required=True, help="JSONL output file (created or overwritten)")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--rpm", type=int, help="override task.rpm")
    run.add_argument("--max-tokens", type=int, help="override task.generation.max_tokens")
    run.add_argument("--scheme", help="override task.generation.scheme (greedy, sample, rejection)")
    run.add_argument("--temperature", type=float, help="override task.generation.temperature")
    run.add_argument("--n", type=int, help="override task.generation.n")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI, returning 0 on success and 1 on a configuration or input error."""
    try:
        args = build_parser().parse_args(argv)
        task = load_task_config(args.config, {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS})
        rows = load_rows(args.input)
        prompts = build_prompts(rows, task)
        summary = asyncio.run(run_task(task, rows, prompts, args.output))
    except (UserError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0

"""Command line entry point: argument parsing and run orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

from .api import ChatClient
from .config import ConfigError, Overrides, TaskConfig, load_config
from .inputs import InputError, load_rows, validate_rows
from .report import build_summary, write_results
from .runner import in_flight_limit, run_rows

USAGE_EXIT_CODE = 1


class _Parser(argparse.ArgumentParser):
    """Argparse parser that reports usage errors with the spec's exit code 1."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"error: {message}\n")
        raise SystemExit(USAGE_EXIT_CODE)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rejector.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a task over a JSONL input file")
    run.add_argument("--config", required=True, type=Path, help="YAML task config")
    run.add_argument("--input", required=True, type=Path, help="JSONL input file")
    run.add_argument("--output", required=True, type=Path, help="JSONL output file")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config, _overrides(args))
        rows = load_rows(args.input)
        validate_rows(rows, config)
    except (ConfigError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    outcomes, summary = asyncio.run(_execute(rows, config))
    write_results(args.output, rows, outcomes, config)
    print(json.dumps(summary))
    return 0


def _overrides(args: argparse.Namespace) -> Overrides:
    return Overrides(
        api_url=args.api_url,
        model=args.model,
        rpm=args.rpm,
        max_tokens=args.max_tokens,
        scheme=args.scheme,
        temperature=args.temperature,
        n=args.n,
    )


async def _execute(rows: list[dict], config: TaskConfig):
    """Run every row against the API and collect the outcomes plus summary."""
    limit = in_flight_limit(config.rpm)
    connector = aiohttp.TCPConnector(limit=limit)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = ChatClient(
            session,
            api_url=config.api_url,
            model=config.model,
            max_tokens=config.generation.max_tokens,
            concurrency=limit,
        )
        outcomes = await run_rows(rows, config, client)
        return outcomes, build_summary(outcomes, client)

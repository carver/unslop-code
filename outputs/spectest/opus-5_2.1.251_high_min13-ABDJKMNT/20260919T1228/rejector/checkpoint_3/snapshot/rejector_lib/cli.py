"""Command line entry point: argument parsing and run orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

from .api import ChatClient
from .config import Overrides, RawConfig, TaskConfig, load_config
from .errors import ConfigError, InputError
from .inputs import load_rows, validate_rows
from .plan import TaskPlan, build_plans, select_task_names
from .report import build_summary, write_results
from .runner import in_flight_limit, run_task

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

    run = subparsers.add_parser("run", help="run one or more tasks over JSONL input")
    run.add_argument("--config", required=True, type=Path, help="YAML task config")
    run.add_argument(
        "--input",
        action="append",
        help="JSONL input file, or <task>=<path> for a multi-task config",
    )
    run.add_argument(
        "--input-dir", type=Path, help="directory holding <task_name>.jsonl files"
    )
    run.add_argument(
        "--output", required=True, type=Path, help="JSONL output file or directory"
    )
    run.add_argument("--task", action="append", help="run only the named task(s)")
    run.add_argument("--api-url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument(
        "--scheme",
        choices=("greedy", "sample", "rejection"),
        help="override generation.scheme",
    )
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--eval-model", help="override the judge model of llm_judge tasks")
    run.add_argument(
        "--num-solutions", type=int, help="override how many solutions each row collects"
    )
    run.add_argument(
        "--icl-strategy",
        choices=("fixed", "random", "round_robin"),
        help="override icl.strategy",
    )
    run.add_argument("--icl-k", type=int, help="override icl.k")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        names = select_task_names(config, args.task or [])
        plans = build_plans(
            config,
            names,
            inputs=args.input or [],
            input_dir=args.input_dir,
            output=args.output,
        )
        jobs = [_prepare(config, plan, _overrides(args)) for plan in plans]
    except (ConfigError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results, summary = asyncio.run(_execute(jobs))
    for plan, result in zip(plans, results):
        write_results(plan.output_path, result)
    print(json.dumps(summary))
    return 0


def _prepare(
    config: RawConfig, plan: TaskPlan, overrides: Overrides
) -> tuple[TaskConfig, list[dict]]:
    """Validate one planned task and read the rows it will run over."""
    task = config.build(plan.name, overrides)
    rows = load_rows(plan.input_path)
    validate_rows(rows, task)
    return task, rows


def _overrides(args: argparse.Namespace) -> Overrides:
    return Overrides(
        api_url=args.api_url,
        model=args.model,
        rpm=args.rpm,
        max_tokens=args.max_tokens,
        scheme=args.scheme,
        temperature=args.temperature,
        n=args.n,
        eval_model=args.eval_model,
        num_solutions=args.num_solutions,
        icl_strategy=args.icl_strategy,
        icl_k=args.icl_k,
    )


async def _execute(jobs: list[tuple[TaskConfig, list[dict]]]):
    """Run every selected task against the API, sharing one client and session."""
    limit = max(1, sum(in_flight_limit(task.rpm) for task, _ in jobs))
    connector = aiohttp.TCPConnector(limit=limit)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = ChatClient(session)
        results = list(
            await asyncio.gather(*(run_task(task, rows, client) for task, rows in jobs))
        )
        return results, build_summary(results, client)

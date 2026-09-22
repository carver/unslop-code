"""Command line entry point: argument parsing and run orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from .api import ChatClient
from .config import Overrides, RawConfig, TaskConfig, load_config
from .cost import track_run
from .errors import ConfigError, InputError
from .estimate import estimate_run
from .inputs import load_rows, validate_rows
from .plan import TaskPlan, build_plans, select_task_names
from .progress import ProgressReporter
from .report import build_summary, write_results
from .resume import resume_point
from .runner import run_task

USAGE_EXIT_CODE = 1


@dataclass
class Job:
    """One task ready to run: its config, the rows left to do, its output."""

    task: TaskConfig
    rows: list[dict]
    output_path: Path
    resumed_from: int = 0


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
    run.add_argument("--rpm", type=int, help="override rate_limits.rpm")
    run.add_argument("--tpm", type=int, help="override rate_limits.tpm")
    run.add_argument(
        "--max-concurrent", type=int, help="override rate_limits.max_concurrent"
    )
    run.add_argument("--budget", type=float, help="override cost.budget")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument(
        "--scheme",
        choices=("greedy", "sample", "rejection", "agentic"),
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
    run.add_argument(
        "--api-type", choices=("chat", "completions"), help="override api_type"
    )
    run.add_argument(
        "--chat-template",
        choices=("chatml", "llama3", "mistral", "zephyr"),
        help="override chat_template",
    )
    run.add_argument(
        "--resume", action="store_true", help="skip rows the output file already holds"
    )
    run.add_argument(
        "--dry-run", action="store_true", help="estimate the run without calling the API"
    )
    run.add_argument(
        "--progress", action="store_true", help="report progress on stderr"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        jobs = _build_jobs(args)
    except (ConfigError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(estimate_run([(job.task, job.rows) for job in jobs])))
        return 0

    results, summary = asyncio.run(_execute(jobs, args))
    for job, result in zip(jobs, results):
        write_results(job.output_path, result, append=args.resume)
    print(json.dumps(summary))
    return 0


def _build_jobs(args: argparse.Namespace) -> list[Job]:
    """Validate every selected task and read the rows it still has to do."""
    config = load_config(args.config)
    names = select_task_names(config, args.task or [])
    plans = build_plans(
        config,
        names,
        inputs=args.input or [],
        input_dir=args.input_dir,
        output=args.output,
    )
    return [_prepare(config, plan, args) for plan in plans]


def _prepare(config: RawConfig, plan: TaskPlan, args: argparse.Namespace) -> Job:
    """Validate one planned task and read the rows it will run over."""
    task = config.build(plan.name, _overrides(args))
    rows = load_rows(plan.input_path)
    validate_rows(rows, task)
    resuming = args.resume and not args.dry_run
    skip = resume_point(plan.output_path, task) if resuming else 0
    return Job(task, rows[skip:], plan.output_path, skip)


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
        api_type=args.api_type,
        chat_template=args.chat_template,
        tpm=args.tpm,
        max_concurrent=args.max_concurrent,
        budget=args.budget,
    )


async def _execute(jobs: list[Job], args: argparse.Namespace):
    """Run every selected task against the API, sharing one client and session."""
    cost = track_run([job.task.cost for job in jobs])
    connector = aiohttp.TCPConnector(
        limit=max(1, sum(job.task.limits.concurrency for job in jobs))
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        client = ChatClient(session, cost)
        progress = _reporter(jobs, client, cost, args.progress)
        ticker = asyncio.create_task(progress.tick())
        results = list(
            await asyncio.gather(
                *(run_task(job.task, job.rows, client, progress) for job in jobs)
            )
        )
        ticker.cancel()
        resumed = sum(job.resumed_from for job in jobs) if args.resume else None
        return results, build_summary(results, client, resumed)


def _reporter(
    jobs: list[Job], client: ChatClient, cost, show_progress: bool
) -> ProgressReporter:
    """The progress reporter, told which of its optional fields to print."""
    return ProgressReporter(
        total=sum(len(job.rows) for job in jobs),
        client=client,
        cost=cost,
        enabled=show_progress,
        show_counts=any(job.task.has_verdict for job in jobs),
    )


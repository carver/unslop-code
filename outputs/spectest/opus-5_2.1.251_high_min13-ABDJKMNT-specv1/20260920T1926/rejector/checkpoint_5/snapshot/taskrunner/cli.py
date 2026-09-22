"""Command line entry point: argument parsing and run orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import ConfigError, RunConfig, load_config
from .cost import CostTracker, is_priced, run_budget
from .dryrun import estimate_run
from .inputs import resolve_inputs, resolve_outputs, select_tasks
from .jsonl import read_rows, write_records
from .progress import ProgressReporter
from .prompts import validate_examples, validate_rows
from .records import build_record, build_summary
from .resume import resume_point
from .runner import TaskJob, execute

# CLI flags that override the matching config value when given.
OVERRIDE_FLAGS = (
    "api_url",
    "model",
    "rpm",
    "tpm",
    "max_concurrent",
    "budget",
    "max_tokens",
    "scheme",
    "temperature",
    "n",
    "eval_model",
    "num_solutions",
    "icl_strategy",
    "icl_k",
    "api_type",
    "chat_template",
)


class _Parser(argparse.ArgumentParser):
    """Argparse variant that reports usage errors with the spec's exit code 1."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise SystemExit(f"{self.prog}: error: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rejector.py")
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    run = subcommands.add_parser("run", help="run one or more tasks over JSONL inputs")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input",
        action="append",
        help="JSONL input file, or '<task>=<path>' for a multi-task config",
    )
    run.add_argument("--input-dir", help="directory holding one <task>.jsonl per task")
    run.add_argument("--output", required=True, help="JSONL output file, or a directory")
    run.add_argument("--task", action="append", help="run only this task; repeatable")
    run.add_argument("--api-url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--eval-model", help="override the judge model of llm_judge tasks")
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
    run.add_argument("--num-solutions", type=int, help="solutions to collect per input row")
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
        help="override chat_template; used by completions requests",
    )
    run.add_argument(
        "--resume", action="store_true", help="skip input rows the output file already holds"
    )
    run.add_argument(
        "--dry-run", action="store_true", help="estimate tokens, cost and time; send nothing"
    )
    run.add_argument("--progress", action="store_true", help="report progress on stderr")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        overrides = {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS}
        config = load_config(args.config, overrides)
        selected = select_tasks(config, args.task)
        inputs = resolve_inputs(config, selected, args.input, args.input_dir)
        outputs = resolve_outputs(config, args.output, selected) if not args.dry_run else {}
        jobs = _build_jobs(config, inputs)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(estimate_run(jobs)))
        return 0

    jobs, skipped = _resume(jobs, outputs) if args.resume else (jobs, None)
    tasks = [job.config for job in jobs]
    tracker = CostTracker(run_budget(tasks))
    results, elapsed = asyncio.run(execute(jobs, tracker, _reporter(jobs, tracker, args)))
    _write(jobs, outputs, results, append=args.resume)
    cost = tracker.summary() if is_priced(tasks) else None
    print(json.dumps(build_summary(results, elapsed, config.multi, cost, skipped)))
    return 0


def _build_jobs(config: RunConfig, inputs: dict) -> list[TaskJob]:
    """Read and validate every selected task's rows before any API traffic."""
    jobs = []
    for name, path in inputs.items():
        task = config.tasks[name]
        rows = read_rows(path)
        label = name if config.multi else ""
        validate_examples(task, label)
        validate_rows(rows, task, label)
        jobs.append(TaskJob(name=name, config=task, rows=rows))
    return jobs


def _resume(jobs: Sequence[TaskJob], outputs: dict[str, Path]) -> tuple[list[TaskJob], int]:
    """Drop the leading rows each task's output file already covers."""
    resumed = []
    skipped = 0
    for job in jobs:
        done = resume_point(outputs[job.name], job.config)
        skipped += done
        resumed.append(TaskJob(name=job.name, config=job.config, rows=job.rows[done:]))
    return resumed, skipped


def _reporter(
    jobs: Sequence[TaskJob], tracker: CostTracker, args: argparse.Namespace
) -> ProgressReporter | None:
    if not args.progress:
        return None
    return ProgressReporter(
        total=sum(len(job.rows) for job in jobs),
        tracker=tracker,
        evaluated=any(job.config.evaluation for job in jobs),
        priced=is_priced(job.config for job in jobs),
    )


def _write(
    jobs: Sequence[TaskJob], outputs: dict[str, Path], results: dict, append: bool
) -> None:
    for job in jobs:
        records = [
            build_record(row, outcome, job.config)
            for row, outcome in zip(job.rows, results[job.name])
        ]
        write_records(outputs[job.name], records, append=append)

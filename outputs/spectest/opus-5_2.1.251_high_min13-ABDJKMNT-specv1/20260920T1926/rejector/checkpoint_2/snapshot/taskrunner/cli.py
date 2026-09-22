"""Command line entry point: argument parsing and run orchestration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from .config import ConfigError, RunConfig, load_config
from .inputs import resolve_inputs, resolve_outputs, select_tasks
from .jsonl import read_rows, write_records
from .prompts import validate_rows
from .records import build_record, build_summary
from .runner import TaskJob, execute

# CLI flags that override the matching config value when given.
OVERRIDE_FLAGS = (
    "api_url",
    "model",
    "rpm",
    "max_tokens",
    "scheme",
    "temperature",
    "n",
    "eval_model",
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
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument(
        "--scheme",
        choices=("greedy", "sample", "rejection"),
        help="override generation.scheme",
    )
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        overrides = {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS}
        config = load_config(args.config, overrides)
        selected = select_tasks(config, args.task)
        inputs = resolve_inputs(config, selected, args.input, args.input_dir)
        outputs = resolve_outputs(config, args.output, selected)
        jobs = _build_jobs(config, inputs)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    results, elapsed = asyncio.run(execute(jobs))
    for job in jobs:
        records = [
            build_record(row, outcome, job.config)
            for row, outcome in zip(job.rows, results[job.name])
        ]
        write_records(outputs[job.name], records)
    print(json.dumps(build_summary(results, elapsed, config.multi)))
    return 0


def _build_jobs(config: RunConfig, inputs: dict) -> list[TaskJob]:
    """Read and validate every selected task's rows before any API traffic."""
    jobs = []
    for name, path in inputs.items():
        task = config.tasks[name]
        rows = read_rows(path)
        validate_rows(rows, task, label=name if config.multi else "")
        jobs.append(TaskJob(name=name, config=task, rows=rows))
    return jobs

#!/usr/bin/env python3
"""CLI entry point: run YAML-configured generation tasks over JSONL files."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from config import API_TYPES, SCHEMES, load_config, overrides_from_flags
from cost import tracker_for
from dataset import write_results
from errors import TaskError
from estimate import estimate_run
from icl import STRATEGIES
from templates import CHAT_TEMPLATES
from jobs import build_jobs
from runner import run_tasks, summarize


def main(argv: list[str] | None = None) -> int:
    """Return the process exit code: 0 on success, 1 on config or input errors."""
    args = _parse_args(argv)
    try:
        config = load_config(args.config, overrides_from_flags(vars(args)), args.task)
        jobs = build_jobs(config, args.input or [], args.input_dir, args.output, args.resume)
    except TaskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(estimate_run(jobs)))
        return 0

    cost = tracker_for(config.tasks)
    results = asyncio.run(run_tasks(jobs, cost, args.progress))
    for job, result in zip(jobs, results):
        write_results(job.output_path, result.records, append=job.resumed_from > 0)
    print(json.dumps(summarize(results, config.multi, cost, args.resume)))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rejector.py", description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run one or more tasks over their input files")
    run.add_argument("--config", required=True, help="path to the YAML task config")
    run.add_argument(
        "--input",
        action="append",
        help="JSONL input path, or '<task>=<path>' for a multi-task config; repeatable",
    )
    run.add_argument("--input-dir", help="directory holding a <task>.jsonl per task")
    run.add_argument(
        "--output", required=True, help="output JSONL file, or a directory for a multi-task config"
    )
    run.add_argument("--task", action="append", help="run only this task; repeatable")
    run.add_argument("--api-url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--rpm", type=int, help="override rate_limits.rpm")
    run.add_argument("--tpm", type=int, help="override rate_limits.tpm")
    run.add_argument("--max-concurrent", type=int, help="override rate_limits.max_concurrent")
    run.add_argument("--budget", type=float, help="override cost.budget")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", help=f"override generation.scheme ({'|'.join(SCHEMES)})")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--eval-model", help="override the judge model of llm_judge tasks")
    run.add_argument("--num-solutions", type=int, help="override num_solutions")
    run.add_argument("--icl-strategy", help=f"override icl.strategy ({'|'.join(STRATEGIES)})")
    run.add_argument("--icl-k", type=int, help="override icl.k, the examples shown per setup")
    run.add_argument("--api-type", help=f"override api_type ({'|'.join(API_TYPES)})")
    run.add_argument(
        "--chat-template", help=f"override chat_template ({'|'.join(CHAT_TEMPLATES)})"
    )
    run.add_argument(
        "--resume", action="store_true", help="skip the input rows the output file already covers"
    )
    run.add_argument(
        "--dry-run", action="store_true", help="estimate the run's tokens, cost and time instead"
    )
    run.add_argument("--progress", action="store_true", help="report progress on stderr")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())

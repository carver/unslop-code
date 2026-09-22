#!/usr/bin/env python3
"""CLI entry point: run YAML-configured generation tasks over JSONL files."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from config import SCHEMES, load_config, overrides_from_flags
from dataset import write_results
from errors import TaskError
from jobs import build_jobs
from runner import run_tasks, summarize


def main(argv: list[str] | None = None) -> int:
    """Return the process exit code: 0 on success, 1 on config or input errors."""
    args = _parse_args(argv)
    try:
        config = load_config(args.config, overrides_from_flags(vars(args)), args.task)
        jobs = build_jobs(config, args.input or [], args.input_dir, args.output)
    except TaskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results = asyncio.run(run_tasks(jobs))
    for job, result in zip(jobs, results):
        write_results(job.output_path, result.records)
    print(json.dumps(summarize(results, config.multi)))
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
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", help=f"override generation.scheme ({'|'.join(SCHEMES)})")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--eval-model", help="override the judge model of llm_judge tasks")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())

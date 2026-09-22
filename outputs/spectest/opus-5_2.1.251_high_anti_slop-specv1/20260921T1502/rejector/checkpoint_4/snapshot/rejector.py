"""CLI entry point: `python rejector.py run --config ... --input ... --output ...`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from config import API_TYPES, SCHEMES, load_config
from icl import STRATEGIES
from templates import TEMPLATES
from errors import UsageError
from jobs import plan_jobs
from jsonl import write_jsonl
from records import summarize
from runner import run_jobs

OVERRIDE_FLAGS = (
    "api_url", "model", "rpm", "scheme", "temperature", "max_tokens", "n", "eval_model",
    "num_solutions", "icl_strategy", "icl_k", "api_type", "chat_template",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rejector", description="Run prompt tasks against an OpenAI compatible API."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="execute a task over a JSONL input file")
    run.add_argument("--config", type=Path, required=True, help="YAML task config")
    run.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="[TASK=]PATH",
        help="JSONL input file; repeat as <task>=<path> for a multi task config",
    )
    run.add_argument(
        "--input-dir", type=Path, help="directory holding <task>.jsonl for each task"
    )
    run.add_argument(
        "--output", type=Path, required=True, help="JSONL output file, or directory for many tasks"
    )
    run.add_argument(
        "--task", action="append", default=[], dest="tasks", help="run only this task (repeatable)"
    )
    run.add_argument("--api-url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--scheme", choices=SCHEMES, help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--eval-model", help="override evaluation.model for llm_judge tasks")
    run.add_argument("--num-solutions", type=int, help="override num_solutions")
    run.add_argument("--icl-strategy", choices=STRATEGIES, help="override icl.strategy")
    run.add_argument("--icl-k", type=int, help="override icl.k")
    run.add_argument("--api-type", choices=API_TYPES, help="override api_type")
    run.add_argument(
        "--chat-template", choices=tuple(TEMPLATES), help="override chat_template"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        overrides = {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS}
        suite = load_config(args.config, overrides, args.tasks)
        jobs = plan_jobs(suite, args.input, args.input_dir, args.output)
        results, elapsed = asyncio.run(run_jobs(jobs))
        for job in jobs:
            write_jsonl(job.output, results[job.config.name].records)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summarize(results, elapsed, per_task=suite.multi)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

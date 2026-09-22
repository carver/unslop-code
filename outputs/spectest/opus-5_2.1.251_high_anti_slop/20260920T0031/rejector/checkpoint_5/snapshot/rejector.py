#!/usr/bin/env python3
"""CLI for running one or more prompt tasks over JSONL datasets.

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

from chat_templates import TEMPLATES
from config import API_TYPES, SCHEMES, load_tasks
from dataset import write_results
from errors import RejectorError
from estimate import estimate
from icl import STRATEGIES
from plan import build_plan
from runner import run_suite

#: Flags that replace the matching config value when provided.
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


class Parser(argparse.ArgumentParser):
    """Argument parser that reports usage problems with the configuration exit code."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="rejector.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run one or more tasks over their JSONL input files")
    run.add_argument("--config", required=True, help="path to the YAML task config")
    run.add_argument(
        "--input",
        action="append",
        metavar="[TASK=]PATH",
        help="JSONL input file; multi-task configs need one <task>=<path> per task",
    )
    run.add_argument("--input-dir", help="directory holding a <task_name>.jsonl file per task")
    run.add_argument("--output", required=True, help="output JSONL file, or a directory for multi-task configs")
    run.add_argument("--task", action="append", help="run only this task; repeat to run several")
    run.add_argument("--api-url", help="override task.api_url")
    run.add_argument("--model", help="override task.model")
    run.add_argument("--eval-model", help="override evaluation.model of every selected llm_judge task")
    run.add_argument("--rpm", type=int, help="override rate_limits.rpm")
    run.add_argument("--tpm", type=int, help="override rate_limits.tpm")
    run.add_argument("--max-concurrent", type=int, help="override rate_limits.max_concurrent")
    run.add_argument("--budget", type=float, help="override cost.budget")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", choices=sorted(SCHEMES), help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--num-solutions", type=int, help="override task.num_solutions")
    run.add_argument("--icl-strategy", choices=list(STRATEGIES), help="override icl.strategy")
    run.add_argument("--icl-k", type=int, help="override icl.k")
    run.add_argument("--api-type", choices=sorted(API_TYPES), help="override task.api_type")
    run.add_argument("--chat-template", choices=sorted(TEMPLATES), help="override task.chat_template")
    run.add_argument("--resume", action="store_true", help="skip the input rows the output file already covers")
    run.add_argument("--dry-run", action="store_true", help="print a token and cost estimate without calling the API")
    run.add_argument("--progress", action="store_true", help="report progress on stderr while the run proceeds")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides: dict[str, Any] = {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS}
    try:
        suite = load_tasks(args.config, overrides, args.task)
        plan = build_plan(suite, args.input or [], args.input_dir, args.output, args.resume)
        if args.dry_run:
            print(json.dumps(estimate(plan)))
            return 0
        results, summary = asyncio.run(run_suite(plan, args.progress))
        for run in plan:
            write_results(run.output_path, results[run.task.name], run.resume_from or 0)
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

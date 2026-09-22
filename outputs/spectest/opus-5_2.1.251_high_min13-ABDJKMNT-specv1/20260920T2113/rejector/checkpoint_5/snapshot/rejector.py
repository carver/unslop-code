"""CLI entry point: run one or more YAML tasks over their JSONL input files."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from rejlib.config import API_TYPES, SCHEMES
from rejlib.dryrun import estimate
from rejlib.errors import ConfigError
from rejlib.icl import STRATEGIES
from rejlib.plan import RunPlan, build_plan, write_results
from rejlib.progress import Progress
from rejlib.rows import build_summary
from rejlib.runner import run_tasks
from rejlib.templates import TEMPLATE_NAMES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rejector.py", description="Run generation tasks over JSONL input files."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run tasks and write one result per input row")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input", action="append", default=[],
        help="JSONL input file, or <task>=<path> for multi-task configs; repeatable",
    )
    run.add_argument("--input-dir", help="directory holding <task_name>.jsonl inputs")
    run.add_argument(
        "--output", required=True,
        help="JSONL output file, or the output directory for multi-task configs",
    )
    run.add_argument("--task", action="append", default=[],
                     help="run only the named task; repeatable")
    run.add_argument("--eval-model", help="override the judge model of llm_judge tasks")
    run.add_argument("--api-url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--rpm", type=int, help="override rate_limits.rpm")
    run.add_argument("--tpm", type=int, help="override rate_limits.tpm")
    run.add_argument("--max-concurrent", type=int,
                     help="override rate_limits.max_concurrent")
    run.add_argument("--budget", type=float, help="override cost.budget")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", choices=SCHEMES, help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--num-solutions", type=int, help="solutions to collect per input row")
    run.add_argument("--icl-strategy", choices=STRATEGIES, help="override icl.strategy")
    run.add_argument("--icl-k", type=int, help="override icl.k")
    run.add_argument("--api-type", choices=API_TYPES, help="override api_type")
    run.add_argument("--chat-template", choices=TEMPLATE_NAMES,
                     help="override chat_template, used by completions requests")
    run.add_argument("--resume", action="store_true",
                     help="skip input rows already complete in the output file")
    run.add_argument("--dry-run", action="store_true",
                     help="estimate tokens, cost and time without calling the API")
    run.add_argument("--progress", action="store_true",
                     help="report progress on stderr while the run proceeds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_plan(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(estimate(plan.config.tasks, plan.rows)))
        return 0

    runs = asyncio.run(
        run_tasks(plan.config.tasks, plan.rows, plan.ledger, _reporter(plan, args.progress))
    )
    write_results(plan, runs)
    print(json.dumps(build_summary(runs, plan.config.multi, plan.ledger, plan.resumed)))
    return 0


def _reporter(plan: RunPlan, enabled: bool) -> Progress | None:
    """The progress reporter, when `--progress` asked for one."""
    if not enabled:
        return None
    return Progress(plan.total_rows, evaluated=plan.evaluated, ledger=plan.ledger)


if __name__ == "__main__":
    sys.exit(main())

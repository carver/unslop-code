"""CLI entry point: run one or more YAML tasks over their JSONL input files."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from rejlib.config import SCHEMES, load_config
from rejlib.errors import ConfigError
from rejlib.icl import STRATEGIES
from rejlib.inputs import prepare_output, resolve_inputs
from rejlib.jsonl import write_rows, write_task_rows
from rejlib.rows import build_summary
from rejlib.runner import run_tasks

OVERRIDES = (
    "api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n", "eval_model",
    "num_solutions", "icl_strategy", "icl_k",
)


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
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", choices=SCHEMES, help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--num-solutions", type=int, help="solutions to collect per input row")
    run.add_argument("--icl-strategy", choices=STRATEGIES, help="override icl.strategy")
    run.add_argument("--icl-k", type=int, help="override icl.k")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(
            args.config, {name: getattr(args, name) for name in OVERRIDES}, args.task
        )
        rows = resolve_inputs(config, args.input, args.input_dir)
        output = prepare_output(config.multi, args.output)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    runs = asyncio.run(run_tasks(config.tasks, rows))
    if config.multi:
        write_task_rows(output, {name: run.rows for name, run in runs.items()})
    else:
        write_rows(output, runs[config.only.name].rows)
    print(json.dumps(build_summary(runs, config.multi)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

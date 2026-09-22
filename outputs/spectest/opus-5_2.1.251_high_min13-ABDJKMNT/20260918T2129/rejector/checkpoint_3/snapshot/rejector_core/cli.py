"""Argument parsing and the `run` command."""

from __future__ import annotations

import argparse
import json
import sys

from .config import SCHEMES, load_config
from .dataset import load_rows
from .errors import RejectorError
from .icl import STRATEGIES
from .paths import resolve_inputs, resolve_outputs
from .prompts import required_fields, validate_rows
from .reporting import build_summary, write_rows
from .runner import run_tasks

OVERRIDE_FLAGS = (
    "api_url", "model", "rpm", "max_tokens", "scheme", "temperature", "n", "eval_model",
    "num_solutions", "icl_strategy", "icl_k",
)


class _ArgumentParser(argparse.ArgumentParser):
    """Reports usage problems with exit code 1, the spec's error code."""

    def error(self, message: str):
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="rejector.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run one or more tasks over JSONL input")
    run.add_argument("--config", required=True, help="YAML task config")
    run.add_argument(
        "--input", action="append", help="JSONL input file, or <task>=<path> for multi-task configs"
    )
    run.add_argument("--input-dir", dest="input_dir", help="directory holding <task_name>.jsonl files")
    run.add_argument("--output", required=True, help="JSONL output file, or a directory per task")
    run.add_argument("--task", action="append", help="run only the named task; repeatable")
    run.add_argument("--api-url", dest="api_url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--max-tokens", dest="max_tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", choices=SCHEMES, help="override generation.scheme")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--eval-model", dest="eval_model", help="override the llm_judge model")
    run.add_argument(
        "--num-solutions", dest="num_solutions", type=int, help="override num_solutions"
    )
    run.add_argument(
        "--icl-strategy", dest="icl_strategy", choices=STRATEGIES, help="override icl.strategy"
    )
    run.add_argument("--icl-k", dest="icl_k", type=int, help="override icl.k")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {key: getattr(args, key) for key in OVERRIDE_FLAGS}

    try:
        config = load_config(args.config, overrides, args.task)
        inputs = resolve_inputs(config, args.input, args.input_dir)
        rows_by_task = {name: load_rows(path) for name, path in inputs.items()}
        for task in config.tasks:
            validate_rows(rows_by_task[task.name], required_fields(task))
        outputs = resolve_outputs(config, args.output)
    except RejectorError as exc:
        print(exc, file=sys.stderr)
        return 1

    runs, stats = run_tasks(list(config.tasks), rows_by_task)
    for run in runs:
        write_rows(outputs[run.task.name], run.outcomes, run.task)
    print(json.dumps(build_summary(runs, stats, per_task=config.multi)))
    return 0

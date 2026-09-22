"""Argument parsing and the `run` command."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .chat_templates import CHAT_TEMPLATES
from .config import API_TYPES, SCHEMES, RunConfig, TaskConfig, load_config
from .dataset import load_rows
from .errors import RejectorError
from .estimate import estimate_run
from .icl import STRATEGIES
from .paths import resolve_inputs, resolve_outputs
from .prompts import required_fields, validate_rows
from .reporting import build_summary, write_rows
from .resume import rows_already_done
from .runner import run_tasks

OVERRIDE_FLAGS = (
    "api_url", "model", "rpm", "tpm", "max_concurrent", "budget", "max_tokens", "scheme",
    "temperature", "n", "eval_model", "num_solutions", "icl_strategy", "icl_k", "api_type",
    "chat_template",
)


@dataclass(frozen=True)
class RunPlan:
    """Everything a run needs once the config and inputs have been read."""

    config: RunConfig
    rows: dict

    @property
    def tasks(self) -> list[TaskConfig]:
        return list(self.config.tasks)


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
    run.add_argument("--rpm", type=int, help="override rate_limits.rpm")
    run.add_argument("--tpm", type=int, help="override rate_limits.tpm")
    run.add_argument(
        "--max-concurrent", dest="max_concurrent", type=int, help="override rate_limits.max_concurrent"
    )
    run.add_argument("--budget", type=float, help="override cost.budget")
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
    run.add_argument("--api-type", dest="api_type", choices=API_TYPES, help="override api_type")
    run.add_argument(
        "--chat-template", dest="chat_template", choices=CHAT_TEMPLATES, help="override chat_template"
    )
    run.add_argument("--resume", action="store_true", help="skip rows the output file already holds")
    run.add_argument("--dry-run", dest="dry_run", action="store_true", help="estimate without calling the API")
    run.add_argument("--progress", action="store_true", help="report progress on stderr")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = _plan(args)
        return _estimate(plan) if args.dry_run else _execute(plan, args)
    except RejectorError as exc:
        print(exc, file=sys.stderr)
        return 1


def _plan(args) -> RunPlan:
    """Load the config and every selected task's input rows."""
    overrides = {key: getattr(args, key) for key in OVERRIDE_FLAGS}
    config = load_config(args.config, overrides, args.task)

    inputs = resolve_inputs(config, args.input, args.input_dir)
    rows = {name: load_rows(path) for name, path in inputs.items()}
    for task in config.tasks:
        validate_rows(rows[task.name], required_fields(task))
    return RunPlan(config, rows)


def _estimate(plan: RunPlan) -> int:
    print(json.dumps(estimate_run(plan.tasks, plan.rows)))
    return 0


def _execute(plan: RunPlan, args) -> int:
    """Run the tasks, write their rows, and print the summary."""
    outputs = resolve_outputs(plan.config, args.output)
    resumed = _resume_points(plan.tasks, outputs, args.resume)
    pending = {task.name: plan.rows[task.name][resumed[task.name]:] for task in plan.tasks}

    runs, stats, costs = run_tasks(plan.tasks, pending, progress=args.progress)
    for run in runs:
        write_rows(outputs[run.task.name], run.outcomes, run.task, append=args.resume)

    summary = build_summary(
        runs, stats, costs, per_task=plan.config.multi, resumed=resumed if args.resume else None
    )
    print(json.dumps(summary))
    return 0


def _resume_points(tasks: list[TaskConfig], outputs: dict, resume: bool) -> dict:
    """How many leading rows each task's output file already covers."""
    if not resume:
        return {task.name: 0 for task in tasks}
    return {task.name: rows_already_done(Path(outputs[task.name]), task) for task in tasks}

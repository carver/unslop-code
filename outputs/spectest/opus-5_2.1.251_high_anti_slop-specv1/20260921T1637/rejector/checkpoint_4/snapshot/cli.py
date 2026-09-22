"""Command line interface: argument parsing and the top-level ``run`` flow."""

import argparse
import asyncio
import json
import sys
from typing import NoReturn

from config import load_config
from errors import UserError
from jobs import build_jobs
from pipeline import run_jobs

#: CLI flags that override the matching config values when provided.
OVERRIDE_FLAGS = (
    "api_url",
    "model",
    "rpm",
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
    """Parser that routes usage errors through the tool's exit-code-1 error path."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        raise UserError(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``rejector.py`` argument parser."""
    parser = _Parser(prog="rejector.py", description="Run generation tasks against a chat completions API.")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run one or more tasks over their JSONL input files")
    run.add_argument("--config", required=True, help="YAML task configuration")
    run.add_argument(
        "--input",
        action="append",
        metavar="PATH_OR_TASK=PATH",
        help="JSONL input file; multi-task configs take <task>=<path> and may repeat the flag",
    )
    run.add_argument("--input-dir", help="directory holding <task_name>.jsonl for each task")
    run.add_argument(
        "--output",
        required=True,
        help="JSONL output file, or the directory receiving <task_name>.jsonl for multi-task configs",
    )
    run.add_argument("--task", action="append", help="run only this task; may be repeated")
    run.add_argument("--api-url", help="override api_url")
    run.add_argument("--model", help="override model")
    run.add_argument("--rpm", type=int, help="override rpm")
    run.add_argument("--max-tokens", type=int, help="override generation.max_tokens")
    run.add_argument("--scheme", help="override generation.scheme (greedy, sample, rejection, agentic)")
    run.add_argument("--temperature", type=float, help="override generation.temperature")
    run.add_argument("--n", type=int, help="override generation.n")
    run.add_argument("--eval-model", help="override the judge model of every llm_judge task")
    run.add_argument("--num-solutions", type=int, help="override num_solutions")
    run.add_argument("--icl-strategy", help="override icl.strategy (fixed, random, round_robin)")
    run.add_argument("--icl-k", type=int, help="override icl.k, the examples shown per setup")
    run.add_argument("--api-type", help="override api_type (chat, completions)")
    run.add_argument("--chat-template", help="override chat_template (chatml, llama3, mistral, zephyr)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI, returning 0 on success and 1 on a configuration or input error."""
    try:
        args = build_parser().parse_args(argv)
        config = load_config(args.config, {flag: getattr(args, flag) for flag in OVERRIDE_FLAGS})
        jobs = build_jobs(
            config,
            inputs=args.input or [],
            input_dir=args.input_dir,
            output=args.output,
            names=args.task or [],
        )
        summary = asyncio.run(run_jobs(jobs, config.multi))
    except (UserError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0

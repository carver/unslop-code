"""Resolving parsed CLI arguments into everything one run needs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rejlib.config import RunConfig, load_config
from rejlib.cost import Ledger, build_ledger
from rejlib.inputs import prepare_output, resolve_inputs
from rejlib.jsonl import write_rows
from rejlib.resume import completed_rows
from rejlib.rows import TaskRun

#: CLI flags that replace the corresponding config value when provided.
OVERRIDES = (
    "api_url", "model", "rpm", "tpm", "max_concurrent", "budget", "max_tokens", "scheme",
    "temperature", "n", "eval_model", "num_solutions", "icl_strategy", "icl_k", "api_type",
    "chat_template",
)


@dataclass(frozen=True)
class RunPlan:
    """What a run will process, where it will write, and what it may spend."""

    config: RunConfig
    #: Rows still to process per task: with `--resume`, the ones not done yet.
    rows: dict[str, list[dict]]
    targets: dict[str, Path]
    ledger: Ledger
    #: Rows already complete per task, or ``None`` when not resuming.
    resumed: dict[str, int] | None = None

    @property
    def total_rows(self) -> int:
        return sum(len(rows) for rows in self.rows.values())

    @property
    def evaluated(self) -> bool:
        """Whether any task judges its responses, which progress lines report."""
        return any(task.evaluation is not None for task in self.config.tasks.values())


def build_plan(args) -> RunPlan:
    """Load the config, read the inputs, and settle where the output goes.

    Everything that can fail on bad configuration or input happens here, before
    any request is sent.
    """
    config = load_config(
        args.config, {name: getattr(args, name) for name in OVERRIDES}, args.task
    )
    rows = resolve_inputs(config, args.input, args.input_dir)
    targets = _targets(config, prepare_output(config.multi, args.output))
    resumed = _resumed(config, targets) if args.resume else None
    if resumed is not None:
        rows = {name: task_rows[resumed[name]:] for name, task_rows in rows.items()}
    return RunPlan(
        config=config,
        rows=rows,
        targets=targets,
        ledger=build_ledger(task.cost for task in config.tasks.values()),
        resumed=resumed,
    )


def write_results(plan: RunPlan, runs: dict[str, TaskRun]) -> None:
    """Write each task's rows to its own output file, appending after a resume."""
    for name, run in runs.items():
        write_rows(plan.targets[name], run.rows, append=plan.resumed is not None)


def _targets(config: RunConfig, output: Path) -> dict[str, Path]:
    """Where each task writes: the `--output` file, or one file per task in it."""
    if not config.multi:
        return {name: output for name in config.tasks}
    return {name: output / f"{name}.jsonl" for name in config.tasks}


def _resumed(config: RunConfig, targets: dict[str, Path]) -> dict[str, int]:
    """How many rows of each task are already complete in its output file."""
    return {
        name: completed_rows(targets[name], task) for name, task in config.tasks.items()
    }

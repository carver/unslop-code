"""Pairing each configured task with its input rows and its output file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import RunConfig, TaskConfig
from dataset import load_rows, prepare_prompts
from errors import InputError
from icl import IclPlan, prepare_plan
from prompts import RenderedPrompt

JSONL_SUFFIX = ".jsonl"


@dataclass(frozen=True)
class TaskJob:
    """One task ready to run: its config, its rows, its ICL setups, and where
    results go."""

    config: TaskConfig
    rows: list[dict[str, Any]]
    prompts: list[RenderedPrompt]
    icl: IclPlan
    output_path: str


def build_jobs(
    config: RunConfig, inputs: list[str], input_dir: str | None, output: str
) -> list[TaskJob]:
    """Resolve the CLI's input and output arguments into one job per task.

    Only the tasks the run selected need an input; files named for tasks that
    were left out are ignored.

    Raises:
        InputError: the arguments do not cover the selected tasks, or a row does
            not match its task's templates.
        ConfigError: an ICL example does not match its task's prompt template.
    """
    inputs_by_task = _input_paths(config, inputs, input_dir)
    outputs_by_task = _output_paths(config, output)
    jobs = []
    for task in config.tasks:
        rows = load_rows(inputs_by_task[task.name])
        jobs.append(
            TaskJob(
                config=task,
                rows=rows,
                prompts=prepare_prompts(rows, task),
                icl=prepare_plan(task.icl, task.prompt.user),
                output_path=outputs_by_task[task.name],
            )
        )
    return jobs


def _input_paths(config: RunConfig, inputs: list[str], input_dir: str | None) -> dict[str, str]:
    """Locate each task's input, from `--input-dir` or from `--input` arguments."""
    if input_dir and inputs:
        raise InputError("--input and --input-dir cannot be combined")
    if input_dir:
        return {task.name: _in_directory(input_dir, task.name) for task in config.tasks}
    if not config.multi:
        if len(inputs) != 1:
            raise InputError("a single-task config takes exactly one --input path")
        return {config.tasks[0].name: inputs[0]}
    return _mapped_inputs(config, inputs)


def _in_directory(input_dir: str, name: str) -> str:
    path = Path(input_dir) / f"{name}{JSONL_SUFFIX}"
    if not path.is_file():
        raise InputError(f"no input for task '{name}': {path} does not exist")
    return str(path)


def _mapped_inputs(config: RunConfig, inputs: list[str]) -> dict[str, str]:
    """Read the `--input <task>=<path>` arguments a multi-task config expects."""
    selected = {task.name for task in config.tasks}
    paths = {}
    for entry in inputs:
        name, separator, path = entry.partition("=")
        if not separator:
            raise InputError(f"--input must be '<task>=<path>' for a multi-task config: {entry}")
        if name in selected:
            paths[name] = path
    missing = sorted(selected - paths.keys())
    if missing:
        raise InputError(f"no input given for task '{missing[0]}'")
    return paths


def _output_paths(config: RunConfig, output: str) -> dict[str, str]:
    """A single file for a single-task config, one file per task otherwise."""
    if not config.multi:
        return {config.tasks[0].name: output}
    directory = Path(output)
    if directory.exists() and not directory.is_dir():
        raise InputError(f"--output must be a directory for a multi-task config: {output}")
    directory.mkdir(parents=True, exist_ok=True)
    return {task.name: str(directory / f"{task.name}{JSONL_SUFFIX}") for task in config.tasks}

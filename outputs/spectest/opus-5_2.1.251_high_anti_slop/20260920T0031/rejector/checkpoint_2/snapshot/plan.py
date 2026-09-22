"""Turning the CLI's input and output arguments into ready-to-run work per task."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from config import TaskConfig, TaskSuite
from dataset import Row, load_rows, prepare_messages
from errors import RejectorError
from templates import Message


@dataclass(frozen=True)
class TaskRun:
    """One task with its loaded rows, rendered prompts and destination file."""

    task: TaskConfig
    rows: list[Row]
    prompts: list[list[Message]]
    output_path: str


def build_plan(suite: TaskSuite, inputs: Sequence[str], input_dir: str | None, output: str) -> list[TaskRun]:
    """Resolve every selected task's input and output file and load its rows."""
    sources = _input_paths(suite, inputs, input_dir)
    destinations = _output_paths(suite, output)

    plan = []
    for task in suite.tasks:
        rows = load_rows(sources[task.name])
        plan.append(TaskRun(task, rows, prepare_messages(rows, task), destinations[task.name]))
    return plan


def _input_paths(suite: TaskSuite, inputs: Sequence[str], input_dir: str | None) -> dict[str, str]:
    """The input file of every selected task, from `--input` mappings or `--input-dir`."""
    if inputs and input_dir:
        raise RejectorError("--input and --input-dir cannot be combined")
    if not inputs and not input_dir:
        raise RejectorError("one of --input or --input-dir is required")

    if input_dir:
        paths = {task.name: os.path.join(input_dir, f"{task.name}.jsonl") for task in suite.tasks}
    else:
        paths = _mapped_paths(suite, inputs)

    missing = [task.name for task in suite.tasks if task.name not in paths]
    if missing:
        raise RejectorError(f"no --input given for task(s): {', '.join(missing)}")
    return paths


def _mapped_paths(suite: TaskSuite, inputs: Sequence[str]) -> dict[str, str]:
    """`--input <task>=<path>` pairs; a single-task config also accepts a bare path."""
    if not suite.multi and len(inputs) == 1 and "=" not in inputs[0]:
        return {suite.tasks[0].name: inputs[0]}

    paths = {}
    for value in inputs:
        name, separator, path = value.partition("=")
        if not separator:
            raise RejectorError(f"--input {value!r} must be given as <task>=<path>")
        if name not in suite.names:
            raise RejectorError(f"--input names unknown task '{name}'")
        paths[name] = path
    return paths


def _output_paths(suite: TaskSuite, output: str) -> dict[str, str]:
    """A single-task config writes one file; a multi-task config writes one per task."""
    if not suite.multi:
        return {suite.tasks[0].name: output}
    os.makedirs(output, exist_ok=True)
    return {task.name: os.path.join(output, f"{task.name}.jsonl") for task in suite.tasks}

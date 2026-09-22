"""Turning a task suite and the CLI's file arguments into the work a run performs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import Suite, TaskConfig
from errors import UsageError
from evaluation import require_row_fields
from icl import Setup
from jsonl import read_jsonl
from prompts import render_all, render_examples


@dataclass(frozen=True)
class Job:
    """One task, its input rows with their rendered prompts, and where results go.

    `icl_turns` holds each setup's example turns, which are row independent and
    so rendered once for the whole task.
    """

    config: TaskConfig
    rows: list[dict]
    messages: list[list[dict]]
    icl_turns: dict[str, list[dict]]
    output: Path

    def messages_for(self, index: int, setup: Setup | None) -> list[dict]:
        """One row's messages, with the setup's examples between the system and user turns."""
        base = self.messages[index]
        if setup is None:
            return base
        return [*base[:-1], *self.icl_turns[setup.name], base[-1]]


def plan_jobs(suite: Suite, inputs: list[str], input_dir: Path | None, output: Path) -> list[Job]:
    """Read and validate every selected task's input, so problems surface before any API call."""
    paths = _input_paths(suite, inputs, input_dir)
    outputs = _output_paths(suite, output)

    jobs = []
    for task in suite.tasks:
        rows = read_jsonl(paths[task.name])
        messages = render_all(task.prompt, rows)
        require_row_fields(task.evaluation, rows)
        turns = render_examples(task.prompt, task.icl)
        jobs.append(Job(task, rows, messages, turns, outputs[task.name]))
    return jobs


def _input_paths(suite: Suite, inputs: list[str], input_dir: Path | None) -> dict[str, Path]:
    """One input file per selected task. Inputs named for unselected tasks are ignored."""
    if not suite.multi:
        return {suite.tasks[0].name: _single_input(inputs, input_dir)}
    if inputs and input_dir is not None:
        raise UsageError("--input and --input-dir cannot be combined")
    if input_dir is not None:
        return {task.name: input_dir / f"{task.name}.jsonl" for task in suite.tasks}

    mapped = _mapped_inputs(inputs)
    missing = [task.name for task in suite.tasks if task.name not in mapped]
    if missing:
        raise UsageError(
            f"no input for task '{missing[0]}': pass --input {missing[0]}=<path> or --input-dir"
        )
    return mapped


def _single_input(inputs: list[str], input_dir: Path | None) -> Path:
    if input_dir is not None:
        raise UsageError("--input-dir needs a multi task config; pass --input <path>")
    if len(inputs) != 1:
        raise UsageError("a single task config takes exactly one --input <path>")
    return Path(inputs[0])


def _mapped_inputs(inputs: list[str]) -> dict[str, Path]:
    paths = {}
    for entry in inputs:
        name, separator, path = entry.partition("=")
        if not separator:
            raise UsageError(f"--input {entry}: a multi task config needs --input <task>=<path>")
        paths[name] = Path(path)
    return paths


def _output_paths(suite: Suite, output: Path) -> dict[str, Path]:
    """A single file for a single task config, one file per task otherwise."""
    if not suite.multi:
        return {suite.tasks[0].name: output}
    if output.exists() and not output.is_dir():
        raise UsageError(f"--output {output} must be a directory for a multi task config")
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise UsageError(f"cannot create output directory {output}: {error.strerror}") from None
    return {task.name: output / f"{task.name}.jsonl" for task in suite.tasks}

"""Selecting the tasks to run and pairing each one with its input rows and output file."""

from dataclasses import dataclass
from pathlib import Path

from config import RunConfig, TaskConfig
from dataset import Messages, Row, build_prompts, load_rows
from errors import UserError
from icl import RenderedSetup, render_setups


@dataclass(frozen=True)
class TaskJob:
    """One task, the rows to run it over, its ICL setups, and the file results go to."""

    task: TaskConfig
    rows: list[Row]
    prompts: list[Messages]
    setups: tuple[RenderedSetup, ...]
    output_path: str


def build_jobs(
    config: RunConfig,
    *,
    inputs: list[str],
    input_dir: str | None,
    output: str,
    names: list[str],
) -> list[TaskJob]:
    """Resolve the task selection, inputs, and outputs into the work the pipeline runs.

    Tasks that ``--task`` leaves out need no input file and produce no output.
    """
    tasks = _selected(config, names)
    sources = _input_paths(tasks, inputs, input_dir, config.multi)
    destinations = _output_paths(tasks, output, config.multi)

    jobs = []
    for task in tasks:
        rows = load_rows(sources[task.name])
        setups = render_setups(task.icl, task.prompt.user)
        jobs.append(TaskJob(task, rows, build_prompts(rows, task), setups, destinations[task.name]))
    return jobs


def _selected(config: RunConfig, names: list[str]) -> list[TaskConfig]:
    """Keep the tasks named by ``--task``, in config order; every task when it is absent."""
    if not names:
        return list(config.tasks)
    defined = {task.name for task in config.tasks}
    unknown = [name for name in names if name not in defined]
    if unknown:
        raise UserError(
            f"--task {', '.join(unknown)}: not defined in the config "
            f"(available: {', '.join(sorted(defined))})"
        )
    return [task for task in config.tasks if task.name in set(names)]


def _input_paths(
    tasks: list[TaskConfig], inputs: list[str], input_dir: str | None, multi: bool
) -> dict[str, str]:
    """Map each selected task to its input file, from ``--input-dir`` or explicit ``--input``."""
    if input_dir and inputs:
        raise UserError("--input and --input-dir cannot be combined")
    if input_dir:
        return {task.name: str(Path(input_dir) / f"{task.name}.jsonl") for task in tasks}
    if not inputs:
        raise UserError("one of --input or --input-dir is required")
    if not multi:
        if len(inputs) > 1:
            raise UserError("--input may only be given once for a single-task config")
        return {tasks[0].name: inputs[0]}
    return _mapped_inputs(tasks, inputs)


def _mapped_inputs(tasks: list[TaskConfig], inputs: list[str]) -> dict[str, str]:
    """Parse ``--input task=path`` pairs; pairs for unselected tasks are ignored."""
    mapped = {}
    for value in inputs:
        name, separator, path = value.partition("=")
        if not separator:
            raise UserError(f"--input {value}: multi-task configs need --input <task>=<path>")
        mapped[name] = path

    missing = [task.name for task in tasks if task.name not in mapped]
    if missing:
        raise UserError(f"no --input given for task(s): {', '.join(missing)}")
    return mapped


def _output_paths(tasks: list[TaskConfig], output: str, multi: bool) -> dict[str, str]:
    """A single file for single-task configs, one ``<task>.jsonl`` per task otherwise."""
    if not multi:
        return {tasks[0].name: output}
    directory = Path(output)
    if directory.exists() and not directory.is_dir():
        raise UserError(f"--output must be a directory for multi-task configs: {output}")
    directory.mkdir(parents=True, exist_ok=True)
    return {task.name: str(directory / f"{task.name}.jsonl") for task in tasks}

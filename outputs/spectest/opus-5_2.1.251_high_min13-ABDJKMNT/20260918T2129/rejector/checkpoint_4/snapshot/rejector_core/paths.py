"""Resolving the input and output file of every task that will run.

Multi-task configs take either explicit `<task>=<path>` mappings or a
directory holding one `<task_name>.jsonl` per task, and write their results
into an output directory.  Single-task configs keep the Part 1 behaviour of
one input path and one output path.
"""

from __future__ import annotations

from pathlib import Path

from .config import RunConfig
from .errors import ConfigError, InputError

INPUT_SUFFIX = ".jsonl"


def resolve_inputs(config: RunConfig, mappings: list[str] | None, input_dir: str | None) -> dict:
    """Map each selected task name to the JSONL file it reads."""
    if mappings and input_dir:
        raise ConfigError("--input and --input-dir are alternative modes; pass only one")
    if not mappings and not input_dir:
        raise ConfigError("an input is required: pass --input or --input-dir")

    names = [task.name for task in config.tasks]
    if input_dir:
        return {name: _in_directory(input_dir, name) for name in names}
    if config.multi:
        return _from_mappings(mappings, names, config.task_names)
    return {names[0]: _single_input(mappings, names[0])}


def resolve_outputs(config: RunConfig, output: str) -> dict:
    """Map each selected task name to the JSONL file it writes."""
    if not config.multi:
        return {config.tasks[0].name: Path(output)}

    directory = Path(output)
    if directory.exists() and not directory.is_dir():
        raise ConfigError(f"--output must be a directory for multi-task configs: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    return {task.name: directory / f"{task.name}{INPUT_SUFFIX}" for task in config.tasks}


def _in_directory(input_dir: str, name: str | None) -> Path:
    if name is None:
        raise ConfigError("--input-dir needs a task name; the config declares none")
    return Path(input_dir) / f"{name}{INPUT_SUFFIX}"


def _from_mappings(mappings: list[str], selected: list[str], declared: tuple) -> dict:
    """Parse `<task>=<path>` pairs, keeping only the tasks that will run."""
    pairs = {}
    for mapping in mappings:
        name, separator, path = mapping.partition("=")
        if not separator:
            raise ConfigError(f"--input must be <task>=<path> for multi-task configs: {mapping}")
        if name not in declared:
            raise ConfigError(f"--input names a task the config does not declare: {name}")
        pairs[name] = Path(path)

    missing = [name for name in selected if name not in pairs]
    if missing:
        raise InputError(f"no input given for task(s): {', '.join(missing)}")
    return {name: pairs[name] for name in selected}


def _single_input(mappings: list[str], name: str | None) -> Path:
    """One path, optionally still written as `<task>=<path>`."""
    if len(mappings) > 1:
        raise ConfigError("single-task configs take exactly one --input")
    prefix = f"{name}="
    value = mappings[0]
    return Path(value[len(prefix):] if value.startswith(prefix) else value)

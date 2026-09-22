"""Works out which tasks run, and which files they read and write."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, RawConfig


@dataclass(frozen=True)
class TaskPlan:
    """One task that will run, with the files it reads from and writes to."""

    name: str
    input_path: Path
    output_path: Path


def select_task_names(config: RawConfig, requested: list[str]) -> list[str]:
    """The tasks to run, in config order; `--task` narrows the set."""
    if not requested:
        return list(config.tasks)
    unknown = [name for name in requested if name not in config.tasks]
    if unknown:
        raise ConfigError(f"unknown task(s): {', '.join(unknown)}")
    return [name for name in config.tasks if name in set(requested)]


def build_plans(
    config: RawConfig,
    names: list[str],
    *,
    inputs: list[str],
    input_dir: Path | None,
    output: Path,
) -> list[TaskPlan]:
    """Pair every selected task with its input file and its output file."""
    sources = _input_paths(config, names, inputs, input_dir)
    outputs = _output_paths(config, names, output)
    return [TaskPlan(name, sources[name], outputs[name]) for name in names]


def _input_paths(
    config: RawConfig, names: list[str], inputs: list[str], input_dir: Path | None
) -> dict[str, Path]:
    """Resolve each selected task's input file from whichever mode is in use."""
    if inputs and input_dir is not None:
        raise ConfigError(
            "--input and --input-dir are alternative modes; use only one"
        )
    if input_dir is not None:
        return {name: input_dir / f"{name}.jsonl" for name in names}
    if not inputs:
        raise ConfigError("one of --input or --input-dir is required")

    mapped = _mapped_inputs(config, inputs)
    missing = [name for name in names if name not in mapped]
    if missing:
        raise ConfigError(f"no --input given for task(s): {', '.join(missing)}")
    return {name: mapped[name] for name in names}


def _mapped_inputs(config: RawConfig, inputs: list[str]) -> dict[str, Path]:
    """Read `--input` values, which name a task unless the config has only one."""
    mapped = {}
    for value in inputs:
        name, _, path = value.partition("=")
        if path and name in config.tasks:
            mapped[name] = Path(path)
        elif config.multi:
            raise ConfigError(
                "--input must be <task>=<path> naming a configured task, "
                f"got {value!r}"
            )
        else:
            mapped[next(iter(config.tasks))] = Path(value)
    return mapped


def _output_paths(
    config: RawConfig, names: list[str], output: Path
) -> dict[str, Path]:
    """A file per task for multi-task configs, the given path for a single one."""
    if not config.multi:
        return {name: output for name in names}
    if output.exists() and not output.is_dir():
        raise ConfigError(
            f"--output must be a directory for multi-task configs: {output}"
        )
    return {name: output / f"{name}.jsonl" for name in names}

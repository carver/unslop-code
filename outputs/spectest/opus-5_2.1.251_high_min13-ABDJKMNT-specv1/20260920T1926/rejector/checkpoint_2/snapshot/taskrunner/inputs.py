"""Resolving which task reads which input file, and where its output goes.

Multi-task runs name inputs either explicitly (`--input <task>=<path>`) or by
convention (`--input-dir <dir>/<task>.jsonl`), and always write one file per
task into an output directory. Single-task configs keep the Part 1 forms.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .config import ConfigError, RunConfig

INPUT_SUFFIX = ".jsonl"


def select_tasks(config: RunConfig, requested: Sequence[str] | None) -> list[str]:
    """The task names to run: every task, or just the `--task` selection."""
    if not requested:
        return list(config.tasks)
    unknown = [name for name in requested if name not in config.tasks]
    if unknown:
        raise ConfigError(
            f"unknown task(s) {', '.join(unknown)}; config defines "
            f"{', '.join(config.tasks)}"
        )
    return list(dict.fromkeys(requested))


def resolve_inputs(
    config: RunConfig,
    selected: Sequence[str],
    inputs: Sequence[str] | None,
    input_dir: str | None,
) -> dict[str, Path]:
    """Map each selected task to its input file."""
    if inputs and input_dir:
        raise ConfigError("--input and --input-dir are alternative modes; use only one")
    if input_dir:
        return {name: Path(input_dir) / f"{name}{INPUT_SUFFIX}" for name in selected}
    if not inputs:
        raise ConfigError("an input is required: use --input or --input-dir")

    mapped = _parse_mapping(config, inputs)
    missing = [name for name in selected if name not in mapped]
    if missing:
        raise ConfigError(f"no input given for task(s) {', '.join(missing)}")
    return {name: mapped[name] for name in selected}


def _parse_mapping(config: RunConfig, inputs: Sequence[str]) -> dict[str, Path]:
    """Read `--input` values, which are `task=path` or a bare single-task path."""
    mapped: dict[str, Path] = {}
    for value in inputs:
        name, separator, path = value.partition("=")
        if not separator:
            name, path = _only_task(config, value), value
        if name not in config.tasks:
            raise ConfigError(f"--input names unknown task '{name}'")
        mapped[name] = Path(path)
    return mapped


def _only_task(config: RunConfig, value: str) -> str:
    """A bare `--input <path>` is the Part 1 form, so the config must hold one task."""
    if config.multi:
        raise ConfigError(
            f"--input must be '<task>=<path>' for multi-task configs, got '{value}'"
        )
    return next(iter(config.tasks))


def resolve_outputs(config: RunConfig, output: str, selected: Sequence[str]) -> dict[str, Path]:
    """Map each selected task to the file its records are written to."""
    if not config.multi:
        return {name: Path(output) for name in selected}

    directory = Path(output)
    if directory.exists() and not directory.is_dir():
        raise ConfigError(f"--output must be a directory for multi-task configs: {output}")
    directory.mkdir(parents=True, exist_ok=True)
    return {name: directory / f"{name}{INPUT_SUFFIX}" for name in selected}

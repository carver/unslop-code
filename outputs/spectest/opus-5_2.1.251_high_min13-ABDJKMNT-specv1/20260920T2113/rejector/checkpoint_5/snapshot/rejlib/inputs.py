"""Turning the CLI's input and output flags into per-task rows and paths."""

from __future__ import annotations

from pathlib import Path

from rejlib.config import RunConfig
from rejlib.errors import ConfigError
from rejlib.jsonl import read_rows
from rejlib.prompts import validate_icl, validate_rows


def resolve_inputs(config: RunConfig, inputs: list[str], input_dir) -> dict[str, list[dict]]:
    """Read and validate one row list per task the run will execute."""
    if config.multi:
        paths = _multi_paths(config, inputs, input_dir)
    else:
        paths = _single_path(config, inputs, input_dir)

    rows = {}
    for name, path in paths.items():
        rows[name] = read_rows(path)
        validate_rows(rows[name], config.tasks[name])
        validate_icl(config.tasks[name])
    return rows


def prepare_output(multi: bool, output) -> Path:
    """Check the ``--output`` target before any request is sent (T34)."""
    path = Path(output)
    if multi and path.exists() and not path.is_dir():
        raise ConfigError(f"--output must be a directory for multi-task configs: {path}")
    return path


def _single_path(config: RunConfig, inputs: list[str], input_dir) -> dict[str, Path]:
    """Part 1 input handling: one ``--input <path>``, taken whole (T33)."""
    if input_dir is not None:
        raise ConfigError("--input-dir is only supported for multi-task configs")
    if len(inputs) != 1:
        raise ConfigError("--input <path> is required exactly once for a single-task config")
    return {next(iter(config.tasks)): Path(inputs[0])}


def _multi_paths(config: RunConfig, inputs: list[str], input_dir) -> dict[str, Path]:
    """Explicit mapping mode and directory mode are alternatives, never combined."""
    if inputs and input_dir is not None:
        raise ConfigError("--input and --input-dir are alternative modes; use only one")
    if input_dir is None:
        return _mapped_paths(config, inputs)

    directory = Path(input_dir)
    paths = {}
    for name in config.tasks:
        path = directory / f"{name}.jsonl"
        if not path.is_file():
            raise ConfigError(f"--input-dir {directory}: no {path.name} for task '{name}'")
        paths[name] = path
    return paths


def _mapped_paths(config: RunConfig, inputs: list[str]) -> dict[str, Path]:
    """``--input <task>=<path>`` entries, ignoring tasks this run does not select."""
    if not inputs:
        raise ConfigError(
            "multi-task configs need --input <task>=<path> entries or --input-dir <dir>"
        )
    paths = {}
    for entry in inputs:
        name, separator, path = entry.partition("=")
        if not separator:
            raise ConfigError(f"--input {entry}: multi-task configs need <task>=<path>")
        if name not in config.names:
            raise ConfigError(f"--input {entry}: config defines no task named '{name}'")
        if name in config.tasks:
            paths[name] = Path(path)

    missing = [name for name in config.tasks if name not in paths]
    if missing:
        raise ConfigError(f"no --input given for task(s): {', '.join(missing)}")
    return paths

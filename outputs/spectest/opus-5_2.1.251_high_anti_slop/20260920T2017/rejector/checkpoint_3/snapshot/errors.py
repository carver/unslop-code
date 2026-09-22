"""Errors that map to the CLI's exit code 1."""


class TaskError(Exception):
    """Base class for user-facing configuration and input problems."""


class ConfigError(TaskError):
    """The YAML task configuration is missing or invalid."""


class InputError(TaskError):
    """The JSONL input file is unreadable or does not match the config."""

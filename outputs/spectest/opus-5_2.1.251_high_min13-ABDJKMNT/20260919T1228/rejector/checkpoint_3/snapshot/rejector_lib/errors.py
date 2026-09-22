"""The two failures that stop a run before or during setup, both exit code 1."""

from __future__ import annotations


class ConfigError(Exception):
    """A task config that cannot be used; reported on stderr with exit code 1."""


class InputError(Exception):
    """A bad input file or a row that cannot satisfy the task; exit code 1."""

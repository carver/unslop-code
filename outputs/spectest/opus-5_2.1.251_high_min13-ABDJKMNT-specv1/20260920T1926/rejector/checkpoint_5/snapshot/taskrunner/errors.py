"""The error every configuration and input problem is reported as."""

from __future__ import annotations


class ConfigError(Exception):
    """Raised for any invalid configuration or input; the CLI exits 1 on it."""

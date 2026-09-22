"""Errors the CLI turns into a stderr message and a non-zero exit code."""


class MvaultError(Exception):
    """Base class for every expected `mvault` failure."""


class VaultError(MvaultError):
    """The vault directory is missing, already present, or not a valid vault."""


class SourceError(MvaultError):
    """Source metadata could not be fetched or did not match the source schema."""

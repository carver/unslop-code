"""The error raised for a vault directory that cannot be used as asked."""


class VaultError(Exception):
    """Raised when a vault is missing, occupied, or holds an unusable catalog."""

"""Vault creation."""

from pathlib import Path

from .catalog import empty_catalog, save_catalog
from .errors import VaultError


def init_vault(name, url):
    """Create the vault directory `name` holding an empty catalog for `url`."""
    directory = Path(name)
    if directory.exists():
        raise VaultError(f"vault '{name}' already exists")

    directory.mkdir(parents=True)
    save_catalog(name, empty_catalog(url))

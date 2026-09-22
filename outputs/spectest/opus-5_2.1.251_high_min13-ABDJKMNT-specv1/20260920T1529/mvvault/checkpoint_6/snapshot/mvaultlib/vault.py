"""Vault lifecycle commands: creating and migrating a vault."""

from pathlib import Path

from .catalog import empty_catalog, load_catalog, save_catalog, sort_entries
from .errors import VaultError
from .source import CATEGORIES
from .versions import VERSION


def init_vault(name, url):
    """Create the vault directory `name` holding an empty catalog for `url`."""
    directory = Path(name)
    if directory.exists():
        raise VaultError(f"vault '{name}' already exists")

    directory.mkdir(parents=True)
    save_catalog(name, empty_catalog(url))


def migrate_vault(name):
    """Convert a v1 or v2 catalog to v3 on disk; a v3 vault is left untouched."""
    catalog, version = load_catalog(name)
    if version == VERSION:
        return

    save_catalog(name, migrated(catalog))


def migrated(catalog):
    """An upgraded catalog as a migration persists it: every category ordered.

    Auto-migration writes the same result, so the ordering rule lives with the
    command that defines it rather than being restated by its callers.
    """
    for category in CATEGORIES:
        sort_entries(catalog[category])
    return catalog
